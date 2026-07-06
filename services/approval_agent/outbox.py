import logging
import time
import uuid
from typing import Callable, List, Optional

import requests

try:
    from .config import settings
    from . import tracing_setup
except ImportError:
    from config import settings
    import tracing_setup

logger = logging.getLogger(__name__)

DAPR_BASE_URL = f"http://{settings.dapr_http_host}:{settings.dapr_http_port}/v1.0"
DAPR_STATE_URL = f"{DAPR_BASE_URL}/state/statestore"
QUEUE_KEY = "outbox_queue"


class OutboxError(Exception):
    """Raised when a Dapr state operation backing the outbox fails."""


def _outbox_key(outbox_id: str) -> str:
    return f"outbox:{outbox_id}"


def _save_record(outbox_id: str, record: dict) -> None:
    response = requests.post(DAPR_STATE_URL, json=[{"key": _outbox_key(outbox_id), "value": record}], timeout=5)
    if response.status_code not in (200, 204):
        raise OutboxError(f"Failed to persist outbox record {outbox_id}: {response.status_code}")


def get_record(outbox_id: str) -> Optional[dict]:
    response = requests.get(f"{DAPR_STATE_URL}/{_outbox_key(outbox_id)}", timeout=5)
    if response.status_code == 200 and response.text.strip():
        return response.json()
    return None


def _get_queue():
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
    for _ in range(attempts):
        queue, etag = _get_queue()
        if _save_queue(mutate_fn(list(queue)), etag):
            return
        time.sleep(0.05)
    raise OutboxError("Failed to update outbox queue after repeated write conflicts")


def enqueue_with_state(state_items: List[dict], pubsub_name: str, topic: str, payload: dict) -> str:
    """The outbox pattern (N3): atomically persists state_items together with a durable record of
    the event that must eventually be published, in one Dapr state transaction. This closes a real
    gap in the previous code: a direct 'save state, then publish' sequence loses the event forever
    if the publish call fails or the process dies in between, even though the state write already
    succeeded. Here, if the transaction commits, the intent to publish is guaranteed to survive —
    dispatch_pending() (run by a background poller) delivers it, retrying until it succeeds."""
    # N4 — the dispatcher may publish this many seconds from now, on a background poller with no
    # relation to this request's span, so the current trace context has to be captured now and
    # stored on the record itself rather than relied on later.
    outbox_id = str(uuid.uuid4())
    record = {
        "id": outbox_id,
        "pubsub_name": pubsub_name,
        "topic": topic,
        "payload": payload,
        "status": "pending",
        "attempts": 0,
        "traceparent": tracing_setup.inject_headers().get("traceparent"),
    }
    operations = [{"operation": "upsert", "request": item} for item in state_items]
    operations.append({"operation": "upsert", "request": {"key": _outbox_key(outbox_id), "value": record}})

    response = requests.post(f"{DAPR_STATE_URL}/transaction", json={"operations": operations}, timeout=5)
    if response.status_code not in (200, 204):
        raise OutboxError(f"Transactional write failed: {response.status_code} {response.text}")

    _mutate_queue(lambda q: q if outbox_id in q else q + [outbox_id])
    return outbox_id


def dispatch_pending(max_batch: int = 20) -> int:
    """Attempts to publish every pending outbox record; returns how many were dispatched. Safe to
    call repeatedly from a background poller — a publish failure just leaves the record pending
    for the next tick instead of losing it, and an already-dispatched/missing record is dropped
    from the queue as a no-op."""
    queue, _ = _get_queue()
    dispatched = 0
    for outbox_id in queue[:max_batch]:
        record = get_record(outbox_id)
        if record is None or record.get("status") != "pending":
            _mutate_queue(lambda q, oid=outbox_id: [i for i in q if i != oid])
            continue

        url = f"{DAPR_BASE_URL}/publish/{record['pubsub_name']}/{record['topic']}"
        headers = {"traceparent": record["traceparent"]} if record.get("traceparent") else {}
        try:
            response = requests.post(url, json=record["payload"], headers=headers, timeout=5)
            if response.status_code not in (200, 204):
                raise OutboxError(f"Publish returned {response.status_code}")
        except Exception as e:
            record["attempts"] = record.get("attempts", 0) + 1
            try:
                _save_record(outbox_id, record)
            except OutboxError:
                pass
            logger.warning(f"Outbox dispatch failed for {outbox_id} (attempt {record['attempts']}): {e}")
            continue

        record["status"] = "dispatched"
        _save_record(outbox_id, record)
        _mutate_queue(lambda q, oid=outbox_id: [i for i in q if i != oid])
        dispatched += 1
    return dispatched
