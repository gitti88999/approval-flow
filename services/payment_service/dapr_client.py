import logging
from typing import Optional

import requests

try:
    from .config import DAPR_STATE_URL, DAPR_PUBSUB_PUBLISH_URL
except ImportError:
    from config import DAPR_STATE_URL, DAPR_PUBSUB_PUBLISH_URL

logger = logging.getLogger(__name__)


class DaprInfrastructureError(Exception):
    """Raised when the Dapr sidecar cannot be reached or returns an unexpected result."""


def get_payment_state(tracking_id: str) -> Optional[dict]:
    """Reads the saga state for a tracking id, or None if it was never recorded."""
    try:
        response = requests.get(f"{DAPR_STATE_URL}/payment:{tracking_id}", timeout=2.0)
    except requests.exceptions.RequestException as e:
        raise DaprInfrastructureError(f"Failed to read payment state: {e}") from e

    if response.status_code == 200 and response.text.strip():
        return response.json()
    return None


def save_payment_state(tracking_id: str, payload: dict) -> None:
    """Persists the saga state for a tracking id. Raises on failure so callers never assume it landed."""
    state_payload = [{"key": f"payment:{tracking_id}", "value": payload}]
    try:
        response = requests.post(DAPR_STATE_URL, json=state_payload, timeout=2.0)
    except requests.exceptions.RequestException as e:
        raise DaprInfrastructureError(f"Failed to persist payment state: {e}") from e

    if response.status_code not in (200, 204):
        raise DaprInfrastructureError(f"Dapr state store returned {response.status_code}: {response.text}")


def publish_outcome(tracking_id: str, outcome_status: str, reason: str) -> None:
    """Publishes the final payment outcome for downstream notification/status consumers."""
    payload = {"tracking_id": tracking_id, "status": outcome_status, "reason": reason}
    try:
        response = requests.post(DAPR_PUBSUB_PUBLISH_URL, json=payload, timeout=2.0)
        if response.status_code not in (200, 204):
            logger.error(f"{tracking_id} - Failed to publish payment outcome. Status: {response.status_code}")
    except requests.exceptions.RequestException as e:
        logger.error(f"{tracking_id} - Failed to publish payment outcome: {e}")
