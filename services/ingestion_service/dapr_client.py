import logging
import sys
import requests
from fastapi import HTTPException, status
from config import DAPR_STATE_URL, DAPR_PUBSUB_URL
from schemas import InvoiceSubmission

logger = logging.getLogger(__name__)

class DaprInfrastructureError(Exception):
    """Custom exception for Dapr communication infrastructure failures."""
    pass

def check_global_duplicate(idempotency_key: str, tracking_id: str) -> bool:
    """Queries Dapr state store to check for duplicate entry history."""
    try:
        response = requests.get(f"{DAPR_STATE_URL}/{idempotency_key}", timeout=2.0)
        if response.status_code == 200 and response.text.strip():
            logger.warning(f"{tracking_id} - Duplicate match found for key: {idempotency_key}")
            return True
        return False
    except requests.exceptions.RequestException as e:
        logger.error(f"{tracking_id} - Dapr state store read failure or timeout: {str(e)}")
        # We raise a custom error to handle it inside the router flow
        raise DaprInfrastructureError("Failed to verify transaction uniqueness.")

def save_idempotency_state(idempotency_key: str, invoice_id: str, tracking_id: str) -> bool:
    """Persists current transaction fingerprint key into the Dapr state store.
    Returns True on success, False on failure — caller must handle failures."""
    state_payload = [{"key": idempotency_key, "value": invoice_id}]
    try:
        response = requests.post(DAPR_STATE_URL, json=state_payload, timeout=2.0)
        if response.status_code in (200, 204):
            return True
        logger.error(f"{tracking_id} - Dapr state store returned unexpected status: {response.status_code}")
        return False
    except requests.exceptions.RequestException as e:
        logger.error(f"{tracking_id} - Inability to write transaction signature state: {str(e)}")
        return False

def publish_to_pubsub(tracking_id: str, invoice: InvoiceSubmission, traceparent: str = None):
    """Publishes the structured event payload (including tracking_id) within the background tasks
    context. traceparent, if given, is the incoming /submit request's own W3C trace header —
    forwarding it here means the async submitted-invoices delivery continues the same distributed
    trace Dapr started for the sync gateway -> ingestion-service call, instead of starting a new,
    disconnected one."""
    payload = invoice.model_dump()
    payload["tracking_id"] = tracking_id
    headers = {"traceparent": traceparent} if traceparent else {}
    try:
        response = requests.post(DAPR_PUBSUB_URL, json=payload, headers=headers, timeout=2.0)
        if response.status_code in [200, 204]:
            logger.info(f"{tracking_id} - Successfully published invoice {invoice.id} to Dapr pub/sub.")
        else:
            logger.error(f"{tracking_id} - Dapr pub/sub returned unexpected status: {response.status_code}")
    except requests.exceptions.RequestException as e:
        logger.error(f"{tracking_id} - Failed to connect to Dapr pub/sub router sidecar: {str(e)}")
