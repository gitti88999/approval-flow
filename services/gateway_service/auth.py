import time

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

try:
    from . import secrets_client, users_store
except ImportError:
    import secrets_client
    import users_store

ALGORITHM = "HS256"
TOKEN_TTL_SECONDS = 3600
ALL_ROLES = {"submitter", "approver", "admin"}
# admin is deliberately excluded: it must never be self-assignable through public signup — the
# only way to get one is the startup bootstrap (register(..., allow_admin=True)), which is not
# reachable from any HTTP route.
SELF_SERVICE_ROLES = {"submitter", "approver"}

_bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def register(username: str, password: str, role: str, *, allow_admin: bool = False) -> str:
    """Signup. Public callers can only self-assign submitter/approver; admin is reserved
    for the startup bootstrap (allow_admin=True), which no route exposes.

    Self-service submitter/approver accounts start "pending" and cannot log in until an admin
    approves them (via decide_pending_user); the bootstrap admin is approved immediately since
    nothing else can approve it. Returns the account's initial status.

    A previously-rejected username can register again (fresh "pending" state) — rejection isn't
    a permanent ban, just "not approved yet"; only a pending/approved username is actually taken."""
    valid_roles = ALL_ROLES if allow_admin else SELF_SERVICE_ROLES
    if not username or not password:
        raise ValueError("username and password are required")
    if role not in valid_roles:
        raise ValueError(f"role must be one of {sorted(valid_roles)}")
    existing = users_store.get_user(username)
    if existing is not None and existing.get("status") != "rejected":
        raise ValueError(f"username '{username}' is already taken")

    initial_status = "approved" if allow_admin else "pending"
    users_store.create_user(username, hash_password(password), role, initial_status)
    if initial_status == "pending":
        users_store.add_to_pending_queue(username)
    return initial_status


def authenticate(username: str, password: str) -> str:
    """Returns the role for valid, approved credentials, raises ValueError otherwise."""
    user = users_store.get_user(username)
    if not user or not verify_password(password, user["password_hash"]):
        raise ValueError("Invalid username or password")

    account_status = user.get("status")
    if account_status == "pending":
        raise ValueError("Account is pending admin approval")
    if account_status == "rejected":
        raise ValueError("Account was rejected by an admin. You can register again to request another review.")
    if account_status != "approved":
        raise ValueError("Account is not active")
    return user["role"]


def list_pending_users() -> list:
    return users_store.list_pending_users()


def decide_pending_user(username: str, approve: bool) -> dict:
    user = users_store.get_user(username)
    if user is None:
        raise LookupError(f"No such user '{username}'")
    if user.get("status") != "pending":
        raise ValueError(f"User '{username}' is not pending (status={user.get('status')})")

    new_status = "approved" if approve else "rejected"
    updated = users_store.update_user_status(username, new_status)
    users_store.remove_from_pending_queue(username)
    return updated


def create_access_token(username: str, role: str) -> str:
    now = int(time.time())
    payload = {"sub": username, "role": role, "iat": now, "exp": now + TOKEN_TTL_SECONDS}
    return jwt.encode(payload, secrets_client.fetch_secret("JWT_SECRET"), algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, secrets_client.fetch_secret("JWT_SECRET"), algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    except secrets_client.SecretFetchError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Auth unavailable: {e}")


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
) -> dict:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    return decode_token(credentials.credentials)


def require_role(*allowed_roles: str):
    """FastAPI dependency factory: 403s unless the caller's JWT role is one of allowed_roles."""

    async def checker(user: dict = Depends(get_current_user)) -> dict:
        if user.get("role") not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{user.get('role')}' is not permitted here; requires one of {allowed_roles}",
            )
        return user

    return checker
