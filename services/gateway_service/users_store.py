import time

import requests

try:
    from .config import DAPR_HOST, DAPR_HTTP_PORT
except ImportError:
    from config import DAPR_HOST, DAPR_HTTP_PORT

DAPR_STATE_URL = f"http://{DAPR_HOST}:{DAPR_HTTP_PORT}/v1.0/state/statestore"
PENDING_QUEUE_KEY = "pending_users_queue"


class UsersStoreError(Exception):
    """Raised when the Dapr state store can't be reached — an infrastructure failure, distinct
    from a business-rule rejection like 'username taken'."""


def _user_key(username: str) -> str:
    return f"user:{username}"


def get_user(username: str):
    try:
        response = requests.get(f"{DAPR_STATE_URL}/{_user_key(username)}", timeout=5)
    except requests.exceptions.RequestException as e:
        raise UsersStoreError(f"Failed to reach Dapr state store: {e}") from e

    if response.status_code == 200 and response.text.strip():
        return response.json()
    return None


def _save_user(user: dict) -> None:
    payload = [{"key": _user_key(user["username"]), "value": user}]
    try:
        response = requests.post(DAPR_STATE_URL, json=payload, timeout=5)
    except requests.exceptions.RequestException as e:
        raise UsersStoreError(f"Failed to reach Dapr state store: {e}") from e

    if response.status_code not in (200, 204):
        raise UsersStoreError(f"Dapr state store returned {response.status_code}")


def create_user(username: str, password_hash: str, role: str, status: str) -> None:
    _save_user(
        {
            "username": username,
            "password_hash": password_hash,
            "role": role,
            "status": status,
        }
    )


def update_user_status(username: str, status: str) -> dict:
    user = get_user(username)
    if user is None:
        raise UsersStoreError(f"User '{username}' not found")
    user["status"] = status
    _save_user(user)
    return user


def _get_queue():
    """Returns (queue_list, etag). etag is None if the key has never been written."""
    response = requests.get(f"{DAPR_STATE_URL}/{PENDING_QUEUE_KEY}", timeout=5)
    if response.status_code == 200 and response.text.strip():
        return response.json(), response.headers.get("ETag")
    return [], None


def _save_queue(queue, etag) -> bool:
    item = {"key": PENDING_QUEUE_KEY, "value": queue}
    if etag:
        item["etag"] = etag
        item["options"] = {"concurrency": "first-write"}
    response = requests.post(DAPR_STATE_URL, json=[item], timeout=5)
    return response.status_code in (200, 204)


def _mutate_queue(mutate_fn, attempts: int = 5) -> None:
    """Applies mutate_fn under optimistic concurrency, retrying if another writer raced us."""
    for _ in range(attempts):
        queue, etag = _get_queue()
        if _save_queue(mutate_fn(list(queue)), etag):
            return
        time.sleep(0.05)
    raise UsersStoreError("Failed to update pending-users queue after repeated write conflicts")


def add_to_pending_queue(username: str) -> None:
    _mutate_queue(lambda q: q if username in q else q + [username])


def remove_from_pending_queue(username: str) -> None:
    _mutate_queue(lambda q: [u for u in q if u != username])


def list_pending_users() -> list:
    queue, _ = _get_queue()
    users = []
    for username in queue:
        user = get_user(username)
        if user and user.get("status") == "pending":
            users.append(user)
    return users
