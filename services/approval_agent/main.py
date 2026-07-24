import asyncio
import logging
import os
from fastapi import FastAPI, HTTPException, Request, status
from pydantic import BaseModel
import httpx

try:
    from . import agent, escalation, outbox
    from .logging_setup import configure_logging, set_correlation_id
    from .tracing_setup import configure_tracing, extract_context
except ImportError:
    import agent
    import escalation
    import outbox
    from logging_setup import configure_logging, set_correlation_id
    from tracing_setup import configure_tracing, extract_context

configure_logging("approval-agent")
tracer = configure_tracing("approval-agent")
logger = logging.getLogger(__name__)
DAPR_STATE_URL = f"http://{os.getenv('DAPR_HTTP_HOST', 'localhost')}:{os.getenv('DAPR_HTTP_PORT', '3500')}/v1.0/state/statestore"

app = FastAPI(title="Approval Agent Service", version="1.0")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.on_event("startup")
async def start_outbox_dispatcher():
    """N3 — background poller that delivers events the outbox has durably recorded but not yet
    published, retrying on every tick until each one succeeds."""
    async def loop():
        while True:
            try:
                dispatched = await asyncio.to_thread(outbox.dispatch_pending)
                if dispatched:
                    logger.info(f"[Outbox] Dispatched {dispatched} pending event(s).")
            except Exception as e:
                logger.error(f"[Outbox] Dispatcher tick failed: {e}")
            await asyncio.sleep(2)

    asyncio.create_task(loop())


async def get_evaluation(tracking_id: str):
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{DAPR_STATE_URL}/invoice_evaluation:{tracking_id}")
    if response.status_code == 200 and response.text.strip():
        return response.json()
    return None


async def save_evaluation(tracking_id: str, record: dict) -> bool:
    async with httpx.AsyncClient() as client:
        response = await client.post(
            DAPR_STATE_URL, json=[{"key": f"invoice_evaluation:{tracking_id}", "value": record}]
        )
    return response.status_code in (200, 204)


@app.get("/dapr/subscribe")
async def subscribe():
    logger.info("!!! DAPR IS ASKING FOR SUBSCRIPTIONS !!!")
    return [
        {
            "pubsubname": "invoice-pubsub",
            "topic": "submitted-invoices",
            "route": "/events/invoice-submissions"
        },
        {
            "pubsubname": "invoice-pubsub",
            "topic": "invoice-completed",
            "route": "/events/payment-outcome"
        }
    ]


@app.post("/events/dlq", status_code=status.HTTP_200_OK)
async def handle_dead_letter_event(request: Request):
    """Minimal DLQ sink: logs poison-pill messages that eventually land in the dead-letter topic."""
    try:
        event_envelope = await request.json()
    except Exception:
        event_envelope = {}
    logger.warning("[Agent DLQ] Received dead-letter event: %s", event_envelope)
    return {"status": "ACCEPTED"}


@app.post("/events/payment-outcome", status_code=status.HTTP_200_OK)
async def handle_payment_outcome(request: Request):
    """Records the payment service's final outcome so GET /status can report it."""
    event_envelope = await request.json()
    event_data = event_envelope.get("data", event_envelope)
    tracking_id = event_data.get("tracking_id")
    if not tracking_id:
        return {"status": "SUCCESS"}
    set_correlation_id(tracking_id)

    parent_ctx = extract_context(event_envelope.get("traceparent"))
    with tracer.start_as_current_span("handle_payment_outcome", context=parent_ctx) as span:
        span.set_attribute("correlation_id", tracking_id)
        record = await get_evaluation(tracking_id) or {"tracking_id": tracking_id}
        record["payment_status"] = event_data.get("status")
        record["payment_reason"] = event_data.get("reason")
        await save_evaluation(tracking_id, record)
        logger.info(f"[Agent] Recorded payment outcome for TrackingID: {tracking_id}: {event_data.get('status')}")
    return {"status": "SUCCESS"}

@app.post("/events/invoice-submissions", status_code=status.HTTP_200_OK)
async def handle_invoice_event(request: Request):
    try:
        event_envelope = await request.json()
        event_data = event_envelope.get("data", {})

        invoice = event_data.get("invoice", event_data) if isinstance(event_data, dict) else event_data
        tracking_id = event_data.get("tracking_id", event_envelope.get("id", "UNKNOWN-ID"))
        set_correlation_id(tracking_id)

        logger.info(f"[Agent Router] Received event: {event_envelope}")
        logger.info("[Agent Router] Digested Payload")

        # N4 — nests this span (and, transitively, the LLM call span agent.py creates) under the
        # same distributed trace Dapr started for this pub/sub delivery, so the whole submit ->
        # evaluate -> pay journey shows up as one trace in Jaeger, tagged with our correlation id.
        parent_ctx = extract_context(event_envelope.get("traceparent"))
        with tracer.start_as_current_span("handle_invoice_submission", context=parent_ctx) as span:
            span.set_attribute("correlation_id", tracking_id)
            evaluation_result = agent.process_invoice_evaluation(invoice, tracking_id)

            state_item = {
                "key": f"invoice_evaluation:{tracking_id}",
                "value": {
                    "tracking_id": tracking_id,
                    "recommendation": evaluation_result.get("recommendation", "human_review"),
                    "reason": evaluation_result.get("reason", ""),
                    "confidence": evaluation_result.get("confidence"),
                },
            }

            if evaluation_result.get("recommendation") == "approve":
                # Outbox pattern: persist the evaluation and the payment-required event in one
                # atomic Dapr state transaction, so the intent to publish can never be silently lost
                # even if the direct publish below fails or the process dies — the background
                # dispatcher will still deliver it. Previously this was a plain "save state, then
                # publish" pair: if the publish call failed, the evaluation was already marked
                # approved with no record that payment was ever supposed to happen — a real, silent
                # lost-money bug.
                try:
                    outbox.enqueue_with_state(
                        [state_item],
                        "invoice-pubsub",
                        "payment-required",
                        {"tracking_id": tracking_id, "invoice": invoice},
                    )
                    logger.info(f"[Agent Router] Persisted evaluation and enqueued payment-required for TrackingID: {tracking_id}")
                except outbox.OutboxError as e:
                    logger.error(f"[Agent Router] Failed to persist evaluation/outbox for TrackingID: {tracking_id}: {e}")
            else:
                try:
                    async with httpx.AsyncClient() as client:
                        response = await client.post(DAPR_STATE_URL, json=[state_item])
                        if response.status_code in [200, 204]:
                            logger.info(f"[Agent DB] Successfully persisted evaluation for TrackingID: {tracking_id}")
                        else:
                            logger.error(f"[Agent DB] Failed. Status: {response.status_code}, Response: {response.text}")
                except Exception as e:
                    logger.error(f"[Agent DB] Error: {str(e)}")

                # Anything the agent doesn't clear for auto-approval pauses here for a human — the
                # agent never auto-rejects on its own; a human makes the final call.
                try:
                    escalation.save_escalation(
                        tracking_id,
                        invoice,
                        evaluation_result.get("recommendation", "human_review"),
                        evaluation_result.get("reason", ""),
                        evaluation_result.get("confidence", 0.0),
                    )
                    logger.info(f"[Agent Router] Escalated TrackingID: {tracking_id} for human review")
                except escalation.EscalationError as e:
                    logger.error(f"[Agent Router] Failed to escalate TrackingID: {tracking_id}: {e}")

        return {"status": "SUCCESS"}
    except Exception as exc:
        logger.exception(f"[Agent Router] Unhandled exception while processing invoice submission for TrackingID {tracking_id if 'tracking_id' in locals() else 'UNKNOWN'}")
        return {"status": "DROP"}


class EscalationDecision(BaseModel):
    action: str  # "approve" | "reject" | "request_info"
    approver: str
    notes: str = ""


class EscalationInfo(BaseModel):
    info: dict


@app.get("/escalations")
async def get_escalations():
    """F4 — the approver queue: only items the system escalated, with the agent's recommendation,
    confidence, and cited reason."""
    return escalation.list_open_escalations()


@app.post("/escalations/{tracking_id}/decide")
async def decide_escalation(tracking_id: str, decision: EscalationDecision):
    """F5 — approve, reject, or send back for more info in one action."""
    set_correlation_id(tracking_id)
    if decision.action not in {"approve", "reject", "request_info"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="action must be approve, reject, or request_info")
    try:
        return escalation.resolve_decision(tracking_id, decision.action, decision.approver, decision.notes)
    except LookupError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except escalation.EscalationError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except outbox.OutboxError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.post("/escalations/{tracking_id}/info")
async def provide_escalation_info(tracking_id: str, payload: EscalationInfo):
    """F5 — the submitter answers a request_info; the item resumes exactly where it paused, back
    in the approver queue."""
    set_correlation_id(tracking_id)
    try:
        return escalation.submit_additional_info(tracking_id, payload.info)
    except LookupError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except escalation.EscalationError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


@app.get("/status/{tracking_id}")
async def get_status(tracking_id: str):
    """F2 — a plain-language status a submitter can check, combining the agent's evaluation,
    any human decision, and the payment outcome."""
    set_correlation_id(tracking_id)
    evaluation = await get_evaluation(tracking_id)
    esc = escalation.get_escalation(tracking_id)

    if evaluation is None and esc is None:
        return {
            "tracking_id": tracking_id,
            "stage": "processing",
            "message": "Your submission is still being processed. Check back in a moment.",
            "recommendation": None,
            "reason": "",
            "confidence": None,
            "payment_status": None,
        }

    source = esc or evaluation
    recommendation = source.get("recommendation", "unknown")
    reason = source.get("reason", "")
    confidence = source.get("confidence")
    payment_status = (evaluation or {}).get("payment_status")
    payment_reason = (evaluation or {}).get("payment_reason")
    esc_status = esc.get("status") if esc else None

    if esc_status == "info_requested":
        stage = "awaiting_info"
        message = f"A reviewer requested more information: {esc.get('approver_notes', '')}"
    elif esc_status == "pending":
        stage = "escalated"
        message = f"Awaiting human review. Reason: {reason}"
    elif esc_status == "rejected":
        stage = "rejected"
        message = f"Rejected by {esc.get('approver', 'a reviewer')}: {esc.get('approver_notes') or reason}"
    elif payment_status == "paid":
        stage = "paid"
        message = "Approved and payment completed."
    elif payment_status == "failed":
        stage = "payment_failed"
        message = f"Approved, but payment failed: {payment_reason}"
    elif recommendation == "approve" or esc_status == "approved":
        stage = "approved_pending_payment"
        message = "Approved; payment is processing."
    else:
        stage = "processing"
        message = "Your submission is still being processed."

    return {
        "tracking_id": tracking_id,
        "stage": stage,
        "message": message,
        "recommendation": recommendation,
        "reason": reason,
        "confidence": confidence,
        "payment_status": payment_status,
    }
