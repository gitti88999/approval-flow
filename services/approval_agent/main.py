import logging
import os
from fastapi import FastAPI, HTTPException, Request, status
from pydantic import BaseModel
import httpx
import agent
import escalation

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
DAPR_STATE_URL = f"http://{os.getenv('DAPR_HTTP_HOST', 'localhost')}:{os.getenv('DAPR_HTTP_PORT', '3500')}/v1.0/state/statestore"
DAPR_PUBSUB_PUBLISH_URL = f"http://{os.getenv('DAPR_HTTP_HOST', 'localhost')}:{os.getenv('DAPR_HTTP_PORT', '3500')}/v1.0/publish/invoice-pubsub/payment-required"

app = FastAPI(title="Approval Agent Service", version="1.0")

@app.get("/dapr/subscribe")
async def subscribe():
    logger.info("!!! DAPR IS ASKING FOR SUBSCRIPTIONS !!!") 
    return [
        {
            "pubsubname": "invoice-pubsub",
            "topic": "submitted-invoices",
            "route": "/events/invoice-submissions"
        }
    ]

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
                "evaluated_at": "2026-06-30"
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
