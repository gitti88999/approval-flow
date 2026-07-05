from unittest.mock import patch, MagicMock

from services.approval_agent import escalation


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


def test_resolve_decision_approve_publishes_payment_required():
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
         patch("services.approval_agent.escalation.requests.post", return_value=_resp(204)) as mock_post:
        result = escalation.resolve_decision("T1", "approve", "mgr@example.com", "looks fine")

    assert result["status"] == "approved"
    published = [
        c for c in mock_post.call_args_list
        if c.args and c.args[0].endswith("/publish/invoice-pubsub/payment-required")
    ]
    assert len(published) == 1
    assert published[0].kwargs["json"]["tracking_id"] == "T1"


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
