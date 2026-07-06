import logging
import time
from typing import Callable, List, Optional

import requests

try:
    from .config import settings
    from . import outbox
except ImportError:
    from config import settings
    import outbox

logger = logging.getLogger(__name__)

DAPR_BASE_URL = f"http://{settings.dapr_http_host}:{settings.dapr_http_port}/v1.0"
DAPR_STATE_URL = f"{DAPR_BASE_URL}/state/statestore"

QUEUE_KEY = "escalation_queue"
OPEN_STATUSES = {"pending", "info_requested"}


class EscalationError(Exception):
    """Raised when an escalation state transition cannot be completed."""


def _escalation_key(tracking_id: str) -> str:
    return f"escalation:{tracking_id}"


def get_escalation(tracking_id: str) -> Optional[dict]:
    """Reads an escalation record from durable Dapr state. Survives a service restart because
    nothing about the pause lives in process memory."""
    response = requests.get(f"{DAPR_STATE_URL}/{_escalation_key(tracking_id)}", timeout=5)
    if response.status_code == 200 and response.text.strip():
        return response.json()
    return None


def _save_escalation(tracking_id: str, record: dict) -> None:
    response = requests.post(
        DAPR_STATE_URL, json=[{"key": _escalation_key(tracking_id), "value": record}], timeout=5
    )
    if response.status_code not in (200, 204):
        raise EscalationError(f"Failed to persist escalation {tracking_id}: {response.status_code}")


def _get_queue():
    """Returns (queue_list, etag). etag is None if the key has never been written."""
    response = requests.get(f"{DAPR_STATE_URL}/{QUEUE_KEY}", timeout=5)
    if response.status_code == 200 and response.text.strip():
        return response.json(), response.headers.get("ETag")
    return [], None


def _save_queue(queue: List[str], etag: Optional[str]) -> bool:
    item = {"key": QUEUE_KEY, "value": queue}
    if etag:
        item["etag"] = etag
        item["options"] = {"concurrency": "first-write"}
    response = requests.post(DAPR_STATE_URL, json=[item], timeout=5)
    return response.status_code in (200, 204)


def _mutate_queue(mutate_fn: Callable[[List[str]], List[str]], attempts: int = 5) -> None:
    """Applies mutate_fn under optimistic concurrency, retrying if another writer raced us."""
    for _ in range(attempts):
        queue, etag = _get_queue()
        if _save_queue(mutate_fn(list(queue)), etag):
            return
        time.sleep(0.05)
    raise EscalationError("Failed to update escalation queue after repeated write conflicts")


def save_escalation(tracking_id: str, invoice: dict, recommendation: str, reason: str, confidence: float) -> None:
    """Pauses the workflow: records the agent's rationale and adds the item to the approver queue."""
    record = {
        "tracking_id": tracking_id,
        "invoice": invoice,
        "recommendation": recommendation,
        "reason": reason,
        "confidence": confidence,
        "status": "pending",
    }
    _save_escalation(tracking_id, record)
    _mutate_queue(lambda q: q if tracking_id in q else q + [tracking_id])


def list_open_escalations() -> List[dict]:
    """The approver queue (F4): only items still awaiting a human decision."""
    queue, _ = _get_queue()
    items = []
    for tracking_id in queue:
        record = get_escalation(tracking_id)
        if record and record.get("status") in OPEN_STATUSES:
            items.append(record)
    return items


def resolve_decision(tracking_id: str, action: str, approver: str, notes: str) -> dict:
    """Applies an approver's decision (F5). 'approve' resumes the workflow exactly where the agent
    paused it, by publishing the same payment-required event the auto-approve path would have sent.
    'reject' terminates the item. 'request_info' pauses for the submitter without removing the
    durable escalation record, so it survives a restart until the submitter responds."""
    record = get_escalation(tracking_id)
    if record is None:
        raise LookupError(f"No escalation found for {tracking_id}")
    if record.get("status") not in OPEN_STATUSES:
        raise EscalationError(f"Escalation {tracking_id} already resolved (status={record.get('status')})")

    # The record's status flips to a terminal value last, once every other step has landed. If a
    # step in between raises, the record is still "pending" (or "info_requested"), so retrying this
    # same call is safe: publishing again is deduped by payment-service, and removing an
    # already-removed id from the queue is a no-op.
    if action == "approve":
        # Outbox pattern (N3): the escalation record's "approved" status and the
        # payment-required event are committed in one atomic Dapr state transaction, so a
        # publish failure can never leave the item marked approved with no record that payment
        # was ever supposed to happen — outbox.dispatch_pending() delivers it, retrying until
        # it succeeds. Previously this called publish directly and only logged on failure.
        updated_record = {**record, "status": "approved", "approver": approver, "approver_notes": notes}
        outbox.enqueue_with_state(
            [{"key": _escalation_key(tracking_id), "value": updated_record}],
            "invoice-pubsub",
            "payment-required",
            {"tracking_id": tracking_id, "invoice": record["invoice"]},
        )
        _mutate_queue(lambda q: [t for t in q if t != tracking_id])
        return updated_record

    if action == "reject":
        _mutate_queue(lambda q: [t for t in q if t != tracking_id])
        record.update({"status": "rejected", "approver": approver, "approver_notes": notes})
        _save_escalation(tracking_id, record)
        return record

    if action == "request_info":
        record.update({"status": "info_requested", "approver": approver, "approver_notes": notes})
        _save_escalation(tracking_id, record)
        return record

    raise ValueError(f"Unknown decision action: {action}")


def submit_additional_info(tracking_id: str, info: dict) -> dict:
    """The submitter answers a request_info (F5): merge the extra fields into the invoice and hand
    the item back to the approver queue, resuming exactly where the pause happened."""
    record = get_escalation(tracking_id)
    if record is None:
        raise LookupError(f"No escalation found for {tracking_id}")
    if record.get("status") != "info_requested":
        raise EscalationError(f"Escalation {tracking_id} is not awaiting info (status={record.get('status')})")

    record["invoice"].update(info)
    record["status"] = "pending"
    _save_escalation(tracking_id, record)
    return record
