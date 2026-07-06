import asyncio
import logging
import os

import httpx
import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

try:
    from . import auth
    from .config import APPROVAL_AGENT_APP_ID, DAPR_INVOKE_BASE_URL, INGESTION_APP_ID
    from .logging_setup import configure_logging, set_correlation_id
except ImportError:
    import auth
    from config import APPROVAL_AGENT_APP_ID, DAPR_INVOKE_BASE_URL, INGESTION_APP_ID
    from logging_setup import configure_logging, set_correlation_id

configure_logging("gateway")
logger = logging.getLogger(__name__)

# key_style="endpoint" buckets by (client, route function) rather than the literal resolved
# URL — the default ("url") would let a client bypass the limit on parameterized routes
# (e.g. /escalations/{tracking_id}/decide) simply by varying the path parameter each request.
limiter = Limiter(key_func=get_remote_address, key_style="endpoint")

app = FastAPI(title="API Gateway", version="1.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


async def invoke(app_id: str, method_path: str, request: Request) -> Response:
    """Forwards the incoming request to a backend service over Dapr's synchronous
    service-invocation building block — the gateway never talks to services directly."""
    url = f"{DAPR_INVOKE_BASE_URL}/{app_id}/method/{method_path}"
    body = await request.body()

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            downstream = await client.request(
                request.method,
                url,
                content=body,
                headers={"Content-Type": request.headers.get("content-type", "application/json")},
            )
    except httpx.RequestError as e:
        logger.error(f"Failed to reach {app_id} for {method_path}: {e}")
        raise HTTPException(status_code=502, detail=f"Upstream service '{app_id}' unreachable: {e}")

    return Response(
        content=downstream.content,
        status_code=downstream.status_code,
        media_type=downstream.headers.get("content-type"),
    )


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.on_event("startup")
async def bootstrap_default_admin():
    """Ensures there's always at least one way into the system: registers a default admin
    account on first startup (a no-op on every later restart, since it already exists). The
    Dapr sidecar may not be up yet when this runs, so retry briefly rather than failing hard."""
    username = os.getenv("DEFAULT_ADMIN_USERNAME", "admin")
    password = os.getenv("DEFAULT_ADMIN_PASSWORD", "admin123")
    for attempt in range(10):
        try:
            auth.register(username, password, "admin", allow_admin=True)
            logger.warning(f"Bootstrapped default admin account '{username}'.")
            return
        except ValueError:
            return  # already exists — nothing to do
        except Exception as e:
            logger.info(f"Waiting for Dapr sidecar to bootstrap admin account (attempt {attempt + 1}): {e}")
            await asyncio.sleep(1)
    logger.error(f"Failed to bootstrap default admin account '{username}' after retries.")


class TokenRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    username: str
    password: str
    role: str


@app.post("/auth/register", status_code=201)
@limiter.limit("10/minute")
async def register_user(request: Request, payload: RegisterRequest):
    """N1 — self-service signup, backed by real user storage (Dapr state), not a fixed roster.
    New submitter/approver accounts start pending until an admin approves them."""
    try:
        account_status = auth.register(payload.username, payload.password, payload.role)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"status": account_status, "username": payload.username, "role": payload.role}


@app.get("/auth/pending-users")
@limiter.limit("60/minute")
async def get_pending_users(request: Request, user: dict = Depends(auth.require_role("admin"))):
    """Admin-only: accounts awaiting approval before they can log in."""
    return auth.list_pending_users()


class PendingUserDecision(BaseModel):
    approve: bool


@app.post("/auth/users/{username}/decide")
@limiter.limit("30/minute")
async def decide_pending_user(
    username: str, request: Request, decision: PendingUserDecision, user: dict = Depends(auth.require_role("admin"))
):
    """Admin-only: approve or reject a pending submitter/approver signup."""
    try:
        return auth.decide_pending_user(username, decision.approve)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@app.post("/auth/token")
@limiter.limit("20/minute")
async def issue_token(request: Request, credentials: TokenRequest):
    """N1 — self-signed JWT, issued for any registered user."""
    try:
        role = auth.authenticate(credentials.username, credentials.password)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))
    token = auth.create_access_token(credentials.username, role)
    return {"access_token": token, "token_type": "bearer", "role": role}


@app.post("/submit")
@limiter.limit("60/minute")
async def submit(request: Request, user: dict = Depends(auth.require_role("submitter", "admin"))):
    return await invoke(INGESTION_APP_ID, "submit", request)


@app.get("/escalations")
@limiter.limit("120/minute")
async def list_escalations(request: Request, user: dict = Depends(auth.require_role("approver", "admin"))):
    return await invoke(APPROVAL_AGENT_APP_ID, "escalations", request)


@app.post("/escalations/{tracking_id}/decide")
@limiter.limit("30/minute")
async def decide_escalation(
    tracking_id: str, request: Request, user: dict = Depends(auth.require_role("approver", "admin"))
):
    set_correlation_id(tracking_id)
    return await invoke(APPROVAL_AGENT_APP_ID, f"escalations/{tracking_id}/decide", request)


@app.post("/escalations/{tracking_id}/info")
@limiter.limit("30/minute")
async def provide_escalation_info(
    tracking_id: str, request: Request, user: dict = Depends(auth.require_role("submitter", "admin"))
):
    set_correlation_id(tracking_id)
    return await invoke(APPROVAL_AGENT_APP_ID, f"escalations/{tracking_id}/info", request)


@app.get("/status/{tracking_id}")
@limiter.limit("120/minute")
async def get_status(tracking_id: str, request: Request, user: dict = Depends(auth.get_current_user)):
    set_correlation_id(tracking_id)
    return await invoke(APPROVAL_AGENT_APP_ID, f"status/{tracking_id}", request)


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
