from unittest.mock import MagicMock, patch

import pytest

from services.gateway_service import users_store


def _resp(status_code=204, body=None, etag=None):
    m = MagicMock()
    m.status_code = status_code
    m.text = "x" if body is not None else ""
    m.headers = {"ETag": etag} if etag else {}
    m.json.return_value = body
    return m


def test_get_user_returns_none_when_missing():
    response = MagicMock(status_code=200, text="")
    with patch.object(users_store.requests, "get", return_value=response):
        assert users_store.get_user("nobody") is None


def test_get_user_returns_stored_record():
    response = MagicMock(status_code=200, text="x")
    response.json.return_value = {"username": "alice", "password_hash": "hash", "role": "submitter"}
    with patch.object(users_store.requests, "get", return_value=response):
        user = users_store.get_user("alice")
    assert user["username"] == "alice"
    assert user["role"] == "submitter"


def test_get_user_raises_on_connection_error():
    import requests as requests_module

    with patch.object(users_store.requests, "get", side_effect=requests_module.exceptions.ConnectionError("boom")):
        with pytest.raises(users_store.UsersStoreError):
            users_store.get_user("alice")


def test_create_user_raises_on_non_2xx():
    response = MagicMock(status_code=500)
    with patch.object(users_store.requests, "post", return_value=response):
        with pytest.raises(users_store.UsersStoreError):
            users_store.create_user("alice", "hash", "submitter", "pending")


def test_create_user_posts_expected_payload():
    response = MagicMock(status_code=204)
    with patch.object(users_store.requests, "post", return_value=response) as mock_post:
        users_store.create_user("alice", "hash", "submitter", "pending")

    payload = mock_post.call_args.kwargs["json"]
    assert payload[0]["key"] == "user:alice"
    assert payload[0]["value"] == {
        "username": "alice",
        "password_hash": "hash",
        "role": "submitter",
        "status": "pending",
    }


def test_update_user_status_merges_and_saves():
    stored = {"username": "alice", "password_hash": "hash", "role": "submitter", "status": "pending"}
    with patch.object(users_store, "get_user", return_value=stored), \
         patch.object(users_store.requests, "post", return_value=_resp(204)) as mock_post:
        result = users_store.update_user_status("alice", "approved")

    assert result["status"] == "approved"
    saved_value = mock_post.call_args.kwargs["json"][0]["value"]
    assert saved_value["status"] == "approved"


def test_update_user_status_raises_when_user_missing():
    with patch.object(users_store, "get_user", return_value=None):
        with pytest.raises(users_store.UsersStoreError):
            users_store.update_user_status("nobody", "approved")


def test_add_to_pending_queue_appends_username():
    with patch.object(users_store.requests, "get", return_value=_resp(200, [], etag="1")), \
         patch.object(users_store.requests, "post", return_value=_resp(204)) as mock_post:
        users_store.add_to_pending_queue("dave")

    saved = mock_post.call_args.kwargs["json"][0]
    assert saved["value"] == ["dave"]
    assert saved["etag"] == "1"


def test_remove_from_pending_queue_removes_username():
    with patch.object(users_store.requests, "get", return_value=_resp(200, ["dave", "erin"])), \
         patch.object(users_store.requests, "post", return_value=_resp(204)) as mock_post:
        users_store.remove_from_pending_queue("dave")

    saved = mock_post.call_args.kwargs["json"][0]
    assert saved["value"] == ["erin"]


def test_list_pending_users_filters_by_status():
    queue_resp = _resp(200, ["dave", "erin"])
    dave = MagicMock(status_code=200, text="x")
    dave.json.return_value = {"username": "dave", "status": "pending"}
    erin = MagicMock(status_code=200, text="x")
    erin.json.return_value = {"username": "erin", "status": "approved"}

    def fake_get(url, timeout=5):
        if url.endswith("pending_users_queue"):
            return queue_resp
        if url.endswith("user:dave"):
            return dave
        return erin

    with patch.object(users_store.requests, "get", side_effect=fake_get):
        pending = users_store.list_pending_users()

    assert [u["username"] for u in pending] == ["dave"]
