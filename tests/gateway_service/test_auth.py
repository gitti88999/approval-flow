from unittest.mock import patch

import pytest
from fastapi import HTTPException

from services.gateway_service import auth

pytestmark = pytest.mark.unit

FAKE_SECRET = "test-secret"


def test_register_rejects_invalid_role():
    with pytest.raises(ValueError):
        auth.register("dave", "password123", "superuser")


def test_register_rejects_duplicate_username():
    with patch.object(auth.users_store, "get_user", return_value={"username": "alice"}):
        with pytest.raises(ValueError):
            auth.register("alice", "password123", "submitter")


def test_register_allows_reregistration_after_rejection():
    """A rejected username isn't permanently blocked — the person can register again."""
    rejected = {"username": "dave", "status": "rejected"}
    with patch.object(auth.users_store, "get_user", return_value=rejected), \
         patch.object(auth.users_store, "create_user") as mock_create, \
         patch.object(auth.users_store, "add_to_pending_queue") as mock_queue:
        result_status = auth.register("dave", "newpassword123", "submitter")

    assert result_status == "pending"
    mock_create.assert_called_once()
    mock_queue.assert_called_once_with("dave")


def test_register_rejects_self_service_admin():
    """A public caller must never be able to grant themselves admin — only the startup
    bootstrap (allow_admin=True) can create one."""
    with patch.object(auth.users_store, "get_user", return_value=None):
        with pytest.raises(ValueError):
            auth.register("mallory", "password123", "admin")


def test_register_allows_admin_only_with_explicit_flag():
    with patch.object(auth.users_store, "get_user", return_value=None), \
         patch.object(auth.users_store, "create_user") as mock_create:
        result_status = auth.register("bootstrap-admin", "password123", "admin", allow_admin=True)

    _, _, role, status = mock_create.call_args.args
    assert role == "admin"
    assert status == "approved"
    assert result_status == "approved"


def test_register_hashes_password_and_stores_user_as_pending():
    with patch.object(auth.users_store, "get_user", return_value=None), \
         patch.object(auth.users_store, "create_user") as mock_create, \
         patch.object(auth.users_store, "add_to_pending_queue") as mock_queue:
        result_status = auth.register("dave", "password123", "submitter")

    username, password_hash, role, status = mock_create.call_args.args
    assert username == "dave"
    assert role == "submitter"
    assert status == "pending"
    assert result_status == "pending"
    assert password_hash != "password123"
    assert auth.verify_password("password123", password_hash)
    mock_queue.assert_called_once_with("dave")


def test_authenticate_valid_credentials_returns_role_when_approved():
    stored = {
        "username": "alice",
        "password_hash": auth.hash_password("submitter123"),
        "role": "submitter",
        "status": "approved",
    }
    with patch.object(auth.users_store, "get_user", return_value=stored):
        assert auth.authenticate("alice", "submitter123") == "submitter"


def test_authenticate_rejects_pending_account():
    stored = {
        "username": "dave",
        "password_hash": auth.hash_password("password123"),
        "role": "submitter",
        "status": "pending",
    }
    with patch.object(auth.users_store, "get_user", return_value=stored):
        with pytest.raises(ValueError):
            auth.authenticate("dave", "password123")


def test_authenticate_rejects_account_with_distinct_message():
    """A rejected account must not be told it's merely 'pending' — that's misleading and gives
    no path forward. It should be told it was rejected and that it can register again."""
    stored = {
        "username": "dave",
        "password_hash": auth.hash_password("password123"),
        "role": "submitter",
        "status": "rejected",
    }
    with patch.object(auth.users_store, "get_user", return_value=stored):
        with pytest.raises(ValueError) as exc_info:
            auth.authenticate("dave", "password123")
    assert "pending" not in str(exc_info.value).lower()
    assert "rejected" in str(exc_info.value).lower()


def test_authenticate_rejects_wrong_password():
    stored = {
        "username": "alice",
        "password_hash": auth.hash_password("submitter123"),
        "role": "submitter",
        "status": "approved",
    }
    with patch.object(auth.users_store, "get_user", return_value=stored):
        with pytest.raises(ValueError):
            auth.authenticate("alice", "wrong-password")


def test_authenticate_rejects_unknown_user():
    with patch.object(auth.users_store, "get_user", return_value=None):
        with pytest.raises(ValueError):
            auth.authenticate("nobody", "whatever")


def test_decide_pending_user_approve():
    stored = {"username": "dave", "role": "submitter", "status": "pending"}
    with patch.object(auth.users_store, "get_user", return_value=stored), \
         patch.object(auth.users_store, "update_user_status", return_value={**stored, "status": "approved"}) as mock_update, \
         patch.object(auth.users_store, "remove_from_pending_queue") as mock_remove:
        result = auth.decide_pending_user("dave", True)

    mock_update.assert_called_once_with("dave", "approved")
    mock_remove.assert_called_once_with("dave")
    assert result["status"] == "approved"


def test_decide_pending_user_reject():
    stored = {"username": "dave", "role": "submitter", "status": "pending"}
    with patch.object(auth.users_store, "get_user", return_value=stored), \
         patch.object(auth.users_store, "update_user_status", return_value={**stored, "status": "rejected"}), \
         patch.object(auth.users_store, "remove_from_pending_queue"):
        result = auth.decide_pending_user("dave", False)

    assert result["status"] == "rejected"


def test_decide_pending_user_raises_for_unknown_user():
    with patch.object(auth.users_store, "get_user", return_value=None):
        with pytest.raises(LookupError):
            auth.decide_pending_user("nobody", True)


def test_decide_pending_user_raises_when_not_pending():
    stored = {"username": "dave", "role": "submitter", "status": "approved"}
    with patch.object(auth.users_store, "get_user", return_value=stored):
        with pytest.raises(ValueError):
            auth.decide_pending_user("dave", True)


def test_create_and_decode_token_round_trip():
    with patch.object(auth.secrets_client, "fetch_secret", return_value=FAKE_SECRET):
        token = auth.create_access_token("alice", "submitter")
        decoded = auth.decode_token(token)

    assert decoded["sub"] == "alice"
    assert decoded["role"] == "submitter"


def test_decode_token_rejects_tampered_token():
    with patch.object(auth.secrets_client, "fetch_secret", return_value=FAKE_SECRET):
        token = auth.create_access_token("alice", "submitter")

    header, payload, signature = token.split(".")
    corrupted_signature = ("A" if signature[0] != "A" else "B") + signature[1:]
    tampered = f"{header}.{payload}.{corrupted_signature}"

    with patch.object(auth.secrets_client, "fetch_secret", return_value=FAKE_SECRET):
        with pytest.raises(HTTPException) as exc_info:
            auth.decode_token(tampered)
    assert exc_info.value.status_code == 401


def test_decode_token_rejects_token_signed_with_different_secret():
    with patch.object(auth.secrets_client, "fetch_secret", return_value="secret-a"):
        token = auth.create_access_token("alice", "submitter")

    with patch.object(auth.secrets_client, "fetch_secret", return_value="secret-b"):
        with pytest.raises(HTTPException) as exc_info:
            auth.decode_token(token)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_require_role_allows_matching_role():
    # require_role(...) returns the dependency function itself; calling it directly with a
    # plain dict (bypassing FastAPI's request cycle) is enough to unit test the role check.
    checker = auth.require_role("approver", "admin")
    result = await checker({"sub": "bob", "role": "approver"})
    assert result["role"] == "approver"


@pytest.mark.asyncio
async def test_require_role_rejects_non_matching_role():
    checker = auth.require_role("approver", "admin")
    with pytest.raises(HTTPException) as exc_info:
        await checker({"sub": "alice", "role": "submitter"})
    assert exc_info.value.status_code == 403
