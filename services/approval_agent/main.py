import logging
import os
from fastapi import FastAPI, HTTPException, Request, status
from pydantic import BaseModel
import httpx

try:
    from . import agent, escalation
except ImportError:
    import agent
    import escalation

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
DAPR_STATE_URL = f"http://{os.getenv('DAPR_HTTP_HOST', 'localhost')}:{os.getenv('DAPR_HTTP_PORT', '3500')}/v1.0/state/statestore"
DAPR_PUBSUB_PUBLISH_URL = f"http://{os.getenv('DAPR_HTTP_HOST', 'localhost')}:{os.getenv('DAPR_HTTP_PORT', '3500')}/v1.0/publish/invoice-pubsub/payment-required"

app = FastAPI(title="Approval Agent Service", version="1.0")

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


@app.post("/events/payment-outcome", status_code=status.HTTP_200_OK)
async def handle_payment_outcome(request: Request):
    """Records the payment service's final outcome so GET /status can report it (F2)."""
    event_envelope = await request.json()
    event_data = event_envelope.get("data", event_envelope)
    tracking_id = event_data.get("tracking_id")
    if not tracking_id:
        return {"status": "SUCCESS"}

    record = await get_evaluation(tracking_id) or {"tracking_id": tracking_id}
    record["payment_status"] = event_data.get("status")
    record["payment_reason"] = event_data.get("reason")
    await save_evaluation(tracking_id, record)
    logger.info(f"[Agent] Recorded payment outcome for TrackingID: {tracking_id}: {event_data.get('status')}")
    return {"status": "SUCCESS"}

@app.post("/events/invoice-submissions", status_code=status.HTTP_200_OK)
async def handle_invoice_event(request: Request):
    logger.info("!!! DAPR EVENT ARRIVED AT AGENT !!!")
    event_envelope = await request.json()
    logger.info(f"[Agent Router] Received event: {event_envelope}")
    event_data = event_envelope.get("data", {})
    
    invoice = event_data.get("invoice", event_data) if isinstance(event_data, dict) else event_data
    tracking_id = event_data.get("tracking_id", event_envelope.get("id", "UNKNOWN-ID"))
        
    logger.info(f"[Agent Router] Digested Payload - TrackingID: {tracking_id}")
    
    evaluation_result = agent.process_invoice_evaluation(invoice, tracking_id)
    
    state_payload = [
        {
            "key": f"invoice_evaluation:{tracking_id}",
            "value": {
                "tracking_id": tracking_id,
                "recommendation": evaluation_result.get("recommendation", "human_review"),
                "reason": evaluation_result.get("reason", ""),
                "confidence": evaluation_result.get("confidence"),
            }
        }
    ]
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(DAPR_STATE_URL, json=state_payload)
            if response.status_code in [200, 204]:
                logger.info(f"[Agent DB] Successfully persisted evaluation for TrackingID: {tracking_id}")
            else:
                logger.error(f"[Agent DB] Failed. Status: {response.status_code}, Response: {response.text}")
    except Exception as e:
        logger.error(f"[Agent DB] Error: {str(e)}")

    if evaluation_result.get("recommendation") == "approve":
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    DAPR_PUBSUB_PUBLISH_URL,
                    json={"tracking_id": tracking_id, "invoice": invoice}
                )
                if response.status_code in [200, 204]:
                    logger.info(f"[Agent Router] Published payment-required event for TrackingID: {tracking_id}")
                else:
                    logger.error(f"[Agent Router] Failed to publish payment-required event. Status: {response.status_code}, Response: {response.text}")
        except Exception as e:
            logger.error(f"[Agent Router] Error publishing payment-required event: {str(e)}")
    else:
        # Anything the agent doesn't clear for auto-approval pauses here for a human — the agent
        # never auto-rejects on its own; a human makes the final call (F6).
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
    if decision.action not in {"approve", "reject", "request_info"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="action must be approve, reject, or request_info")
    try:
        return escalation.resolve_decision(tracking_id, decision.action, decision.approver, decision.notes)
    except LookupError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except escalation.EscalationError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


@app.post("/escalations/{tracking_id}/info")
async def provide_escalation_info(tracking_id: str, payload: EscalationInfo):
    """F5 — the submitter answers a request_info; the item resumes exactly where it paused, back
    in the approver queue."""
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
