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
    from .bulkhead import Bulkhead
    from .config import APPROVAL_AGENT_APP_ID, DAPR_INVOKE_BASE_URL, INGESTION_APP_ID
    from .logging_setup import configure_logging, set_correlation_id
except ImportError:
    import auth
    from bulkhead import Bulkhead
    from config import APPROVAL_AGENT_APP_ID, DAPR_INVOKE_BASE_URL, INGESTION_APP_ID
    from logging_setup import configure_logging, set_correlation_id

configure_logging("gateway")
logger = logging.getLogger(__name__)

# key_style="endpoint" buckets by (client, route function) rather than the literal resolved
# URL — the default ("url") would let a client bypass the limit on parameterized routes
# (e.g. /escalations/{tracking_id}/decide) simply by varying the path parameter each request.
limiter = Limiter(key_func=get_remote_address, key_style="endpoint")

app = FastAPI(
    title="ApprovalFlow API Gateway",
    version="1.0",
    description=(
        "Single external entry point for ApprovalFlow (M6). Every route below except `/health` "
        "and `/auth/*` requires a Bearer token — call `POST /auth/token` first, then click "
        "**Authorize** above and paste the `access_token` to try the other routes here."
    ),
    openapi_tags=[
        {"name": "Auth", "description": "Registration, login, and admin approval of new accounts (N1)."},
        {"name": "Submissions", "description": "Submit an expense/invoice (F1)."},
        {"name": "Escalations", "description": "The human-in-the-loop approver queue (F4/F5)."},
        {"name": "Status", "description": "Check a submission's outcome (F2)."},
    ],
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Bulkhead (N3): one bucket of concurrency per downstream app, so a slow/overloaded
# ingestion-service can't also starve calls to approval-agent (or vice versa) by consuming all of
# the gateway's outbound capacity. Full is a fast, explicit 503, not an unbounded queue.
_BULKHEAD_LIMIT = int(os.getenv("BULKHEAD_MAX_CONCURRENT_PER_SERVICE", "20"))
_bulkheads = {
    INGESTION_APP_ID: Bulkhead(_BULKHEAD_LIMIT),
    APPROVAL_AGENT_APP_ID: Bulkhead(_BULKHEAD_LIMIT),
}


async def invoke(app_id: str, method_path: str, request: Request) -> Response:
    """Forwards the incoming request to a backend service over Dapr's synchronous
    service-invocation building block — the gateway never talks to services directly."""
    bulkhead = _bulkheads.get(app_id)
    if bulkhead is not None and not await bulkhead.try_enter():
        logger.warning(f"Bulkhead full for '{app_id}' ({bulkhead.in_use}/{_BULKHEAD_LIMIT} in use)")
        raise HTTPException(
            status_code=503, detail=f"Too many concurrent requests to '{app_id}' — try again shortly."
        )

    try:
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
    finally:
        if bulkhead is not None:
            await bulkhead.exit()


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


@app.post("/auth/register", status_code=201, tags=["Auth"], summary="Register a new account")
@limiter.limit("10/minute")
async def register_user(request: Request, payload: RegisterRequest):
    """N1 — self-service signup, backed by real user storage (Dapr state), not a fixed roster.
    New submitter/approver accounts start pending until an admin approves them. `role: admin`
    is always rejected here — the only admin account is bootstrapped on gateway startup."""
    try:
        account_status = auth.register(payload.username, payload.password, payload.role)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"status": account_status, "username": payload.username, "role": payload.role}


@app.get("/auth/pending-users", tags=["Auth"], summary="List pending signups (admin only)")
@limiter.limit("60/minute")
async def get_pending_users(request: Request, user: dict = Depends(auth.require_role("admin"))):
    """Admin-only: accounts awaiting approval before they can log in."""
    return auth.list_pending_users()


class PendingUserDecision(BaseModel):
    approve: bool


@app.post("/auth/users/{username}/decide", tags=["Auth"], summary="Approve or reject a pending signup (admin only)")
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


@app.post("/auth/token", tags=["Auth"], summary="Log in and get a Bearer token")
@limiter.limit("20/minute")
async def issue_token(request: Request, credentials: TokenRequest):
    """N1 — self-signed JWT, issued for any registered, approved user."""
    try:
        role = auth.authenticate(credentials.username, credentials.password)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))
    token = auth.create_access_token(credentials.username, role)
    return {"access_token": token, "token_type": "bearer", "role": role}


_SUBMIT_EXAMPLE = {
    "id": "INV-1001",
    "submitter": "alice@example.com",
    "department": "engineering",
    "vendor": "Corner Bistro",
    "vendorKnown": True,
    "invoiceNumber": "CB-4471",
    "currency": "USD",
    "category": "meals",
    "attendees": 1,
    "lineItems": [{"description": "Team lunch", "quantity": 1, "unitPrice": 42.0}],
    "taxAmount": 0,
    "total": 42.0,
    "receiptPresent": True,
    "date": "2026-07-05",
    "notes": "",
}


@app.post(
    "/submit",
    tags=["Submissions"],
    summary="Submit an expense/invoice",
    description="Requires role submitter or admin. Forwarded to ingestion-service, which "
    "validates the payload and returns 202 immediately with a tracking id (F1).",
    openapi_extra={
        "requestBody": {
            "content": {"application/json": {"example": _SUBMIT_EXAMPLE}},
            "required": True,
        }
    },
)
@limiter.limit("60/minute")
async def submit(request: Request, user: dict = Depends(auth.require_role("submitter", "admin"))):
    return await invoke(INGESTION_APP_ID, "submit", request)


@app.get(
    "/escalations",
    tags=["Escalations"],
    summary="List the approver queue",
    description="Requires role approver or admin. Only items the system escalated (F4).",
)
@limiter.limit("120/minute")
async def list_escalations(request: Request, user: dict = Depends(auth.require_role("approver", "admin"))):
    return await invoke(APPROVAL_AGENT_APP_ID, "escalations", request)


@app.post(
    "/escalations/{tracking_id}/decide",
    tags=["Escalations"],
    summary="Approve, reject, or request info",
    description="Requires role approver or admin (F5).",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "example": {"action": "approve", "approver": "bob", "notes": "Looks fine"}
                }
            },
            "required": True,
        }
    },
)
@limiter.limit("30/minute")
async def decide_escalation(
    tracking_id: str, request: Request, user: dict = Depends(auth.require_role("approver", "admin"))
):
    set_correlation_id(tracking_id)
    return await invoke(APPROVAL_AGENT_APP_ID, f"escalations/{tracking_id}/decide", request)


@app.post(
    "/escalations/{tracking_id}/info",
    tags=["Escalations"],
    summary="Submitter answers a request_info",
    description="Requires role submitter or admin — resumes the item back into the approver "
    "queue (F5).",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {"example": {"info": {"business_justification": "Client dinner"}}}
            },
            "required": True,
        }
    },
)
@limiter.limit("30/minute")
async def provide_escalation_info(
    tracking_id: str, request: Request, user: dict = Depends(auth.require_role("submitter", "admin"))
):
    set_correlation_id(tracking_id)
    return await invoke(APPROVAL_AGENT_APP_ID, f"escalations/{tracking_id}/info", request)


@app.get(
    "/status/{tracking_id}",
    tags=["Status"],
    summary="Check a submission's status",
    description="Any authenticated role. A plain-language stage + reason (F2).",
)
@limiter.limit("120/minute")
async def get_status(tracking_id: str, request: Request, user: dict = Depends(auth.get_current_user)):
    set_correlation_id(tracking_id)
    return await invoke(APPROVAL_AGENT_APP_ID, f"status/{tracking_id}", request)


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
