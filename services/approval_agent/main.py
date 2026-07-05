import logging
import os
from fastapi import FastAPI, Request, status
import httpx
import agent

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
DAPR_STATE_URL = f"http://{os.getenv('DAPR_HTTP_HOST', 'localhost')}:{os.getenv('DAPR_HTTP_PORT', '3500')}/v1.0/state/statestore"

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
        
    return {"status": "SUCCESS"}
