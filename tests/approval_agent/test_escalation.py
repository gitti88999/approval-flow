from unittest.mock import patch, MagicMock

import pytest

from services.approval_agent import escalation

pytestmark = pytest.mark.unit


def _resp(status_code=204, body=None, etag=None):
    m = MagicMock()
    m.status_code = status_code
    m.text = "x" if body is not None else ""
    m.headers = {"ETag": etag} if etag else {}
    m.json.return_value = body
    return m


def test_save_escalation_persists_record_and_enqueues():
    queue_get = _resp(200, [], etag="1")
    with patch("services.approval_agent.escalation.requests.get", return_value=queue_get) as mock_get, \
         patch("services.approval_agent.escalation.requests.post", return_value=_resp(204)) as mock_post:
        escalation.save_escalation("T1", {"total": 100}, "human_review", "over ceiling", 1.0)

    # first POST persists the escalation record, second persists the updated queue
    assert mock_post.call_count == 2
    record_call, queue_call = mock_post.call_args_list
    assert record_call.kwargs["json"][0]["key"] == "escalation:T1"
    assert queue_call.kwargs["json"][0]["value"] == ["T1"]


def test_list_open_escalations_filters_by_status():
    queue_resp = _resp(200, ["T1", "T2"])
    pending = MagicMock(status_code=200, text="x")
    pending.json.return_value = {"tracking_id": "T1", "status": "pending"}
    resolved = MagicMock(status_code=200, text="x")
    resolved.json.return_value = {"tracking_id": "T2", "status": "approved"}

    def fake_get(url, timeout=5):
        if url.endswith("escalation_queue"):
            return queue_resp
        if url.endswith("escalation:T1"):
            return pending
        return resolved

    with patch("services.approval_agent.escalation.requests.get", side_effect=fake_get):
        open_items = escalation.list_open_escalations()

    assert [item["tracking_id"] for item in open_items] == ["T1"]


def test_resolve_decision_approve_enqueues_outbox_event():
    """resolve_decision no longer publishes directly — it hands the escalation-record update and
    the payment-required event to the outbox as one atomic unit."""
    record_resp = MagicMock(status_code=200, text="x")
    record_resp.json.return_value = {
        "tracking_id": "T1",
        "status": "pending",
        "invoice": {"total": 100},
    }
    queue_resp = _resp(200, ["T1"])

    def fake_get(url, timeout=5):
        if url.endswith("escalation_queue"):
            return queue_resp
        return record_resp

    with patch("services.approval_agent.escalation.requests.get", side_effect=fake_get), \
         patch("services.approval_agent.escalation.requests.post", return_value=_resp(204)), \
         patch.object(escalation.outbox, "enqueue_with_state") as mock_enqueue:
        result = escalation.resolve_decision("T1", "approve", "mgr@example.com", "looks fine")

    assert result["status"] == "approved"
    mock_enqueue.assert_called_once()
    state_items, pubsub_name, topic, payload = mock_enqueue.call_args.args
    assert state_items[0]["key"] == "escalation:T1"
    assert state_items[0]["value"]["status"] == "approved"
    assert pubsub_name == "invoice-pubsub"
    assert topic == "payment-required"
    assert payload == {"tracking_id": "T1", "invoice": {"total": 100}}


def test_resolve_decision_on_already_resolved_raises():
    record_resp = MagicMock(status_code=200, text="x")
    record_resp.json.return_value = {"tracking_id": "T1", "status": "approved", "invoice": {}}

    with patch("services.approval_agent.escalation.requests.get", return_value=record_resp):
        try:
            escalation.resolve_decision("T1", "approve", "mgr@example.com", "")
            assert False, "expected EscalationError"
        except escalation.EscalationError:
            pass


def test_submit_additional_info_resumes_to_pending():
    record_resp = MagicMock(status_code=200, text="x")
    record_resp.json.return_value = {
        "tracking_id": "T1",
        "status": "info_requested",
        "invoice": {"total": 600},
    }

    with patch("services.approval_agent.escalation.requests.get", return_value=record_resp), \
         patch("services.approval_agent.escalation.requests.post", return_value=_resp(204)) as mock_post:
        result = escalation.submit_additional_info("T1", {"business_justification": "client dinner"})

    assert result["status"] == "pending"
    assert result["invoice"]["business_justification"] == "client dinner"
    mock_post.assert_called_once()
