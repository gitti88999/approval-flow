from unittest.mock import MagicMock, patch

import pytest

from services.approval_agent import outbox


def _resp(status_code=204, body=None, etag=None):
    m = MagicMock()
    m.status_code = status_code
    m.text = "x" if body is not None else ""
    m.headers = {"ETag": etag} if etag else {}
    m.json.return_value = body
    return m


def test_enqueue_with_state_writes_transaction_and_queue():
    with patch.object(outbox.requests, "post", return_value=_resp(204)) as mock_post, \
         patch.object(outbox.requests, "get", return_value=_resp(200, [], etag="1")):
        outbox_id = outbox.enqueue_with_state(
            [{"key": "invoice_evaluation:T1", "value": {"status": "approve"}}],
            "invoice-pubsub",
            "payment-required",
            {"tracking_id": "T1"},
        )

    transaction_call = mock_post.call_args_list[0]
    assert transaction_call.args[0].endswith("/state/statestore/transaction")
    operations = transaction_call.kwargs["json"]["operations"]
    assert operations[0]["request"]["key"] == "invoice_evaluation:T1"
    assert operations[1]["request"]["key"] == f"outbox:{outbox_id}"
    assert operations[1]["request"]["value"]["status"] == "pending"

    queue_call = mock_post.call_args_list[1]
    assert queue_call.kwargs["json"][0]["value"] == [outbox_id]


def test_enqueue_with_state_raises_on_transaction_failure():
    with patch.object(outbox.requests, "post", return_value=_resp(500)):
        with pytest.raises(outbox.OutboxError):
            outbox.enqueue_with_state([{"key": "x", "value": {}}], "invoice-pubsub", "topic", {})


def test_dispatch_pending_publishes_and_marks_dispatched():
    queue_resp = _resp(200, ["abc"])
    record = {"id": "abc", "pubsub_name": "invoice-pubsub", "topic": "payment-required", "payload": {"x": 1}, "status": "pending", "attempts": 0}
    record_resp = MagicMock(status_code=200, text="x")
    record_resp.json.return_value = record

    def fake_get(url, timeout=5):
        if url.endswith("outbox_queue"):
            return queue_resp
        return record_resp

    with patch.object(outbox.requests, "get", side_effect=fake_get), \
         patch.object(outbox.requests, "post", return_value=_resp(204)) as mock_post:
        dispatched = outbox.dispatch_pending()

    assert dispatched == 1
    publish_calls = [c for c in mock_post.call_args_list if "/publish/" in c.args[0]]
    assert len(publish_calls) == 1
    assert publish_calls[0].kwargs["json"] == {"x": 1}


def test_dispatch_pending_leaves_record_pending_on_publish_failure():
    queue_resp = _resp(200, ["abc"])
    record = {"id": "abc", "pubsub_name": "invoice-pubsub", "topic": "payment-required", "payload": {"x": 1}, "status": "pending", "attempts": 0}
    record_resp = MagicMock(status_code=200, text="x")
    record_resp.json.return_value = record

    def fake_get(url, timeout=5):
        if url.endswith("outbox_queue"):
            return queue_resp
        return record_resp

    def fake_post(url, json=None, timeout=5):
        if "/publish/" in url:
            return _resp(500)
        return _resp(204)

    with patch.object(outbox.requests, "get", side_effect=fake_get), \
         patch.object(outbox.requests, "post", side_effect=fake_post) as mock_post:
        dispatched = outbox.dispatch_pending()

    assert dispatched == 0
    # the record gets re-saved with an incremented attempt count, still pending
    save_calls = [c for c in mock_post.call_args_list if "/publish/" not in c.args[0] and "outbox_queue" not in str(c.kwargs.get("json"))]
    saved_value = save_calls[-1].kwargs["json"][0]["value"]
    assert saved_value["status"] == "pending"
    assert saved_value["attempts"] == 1


def test_dispatch_pending_removes_missing_record_from_queue():
    queue_resp = _resp(200, ["gone"])
    missing_resp = _resp(200, None)  # empty body -> get_record() returns None

    def fake_get(url, timeout=5):
        return queue_resp if url.endswith("outbox_queue") else missing_resp

    with patch.object(outbox.requests, "get", side_effect=fake_get), \
         patch.object(outbox.requests, "post", return_value=_resp(204)) as mock_post:
        dispatched = outbox.dispatch_pending()

    assert dispatched == 0
    # queue should have been rewritten without "gone"
    queue_write = mock_post.call_args_list[-1]
    assert queue_write.kwargs["json"][0]["value"] == []
