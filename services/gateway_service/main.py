import logging

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

try:
    from .config import APPROVAL_AGENT_APP_ID, DAPR_INVOKE_BASE_URL, INGESTION_APP_ID
    from .logging_setup import configure_logging, set_correlation_id
except ImportError:
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


@app.post("/submit")
@limiter.limit("60/minute")
async def submit(request: Request):
    return await invoke(INGESTION_APP_ID, "submit", request)


@app.get("/escalations")
@limiter.limit("120/minute")
async def list_escalations(request: Request):
    return await invoke(APPROVAL_AGENT_APP_ID, "escalations", request)


@app.post("/escalations/{tracking_id}/decide")
@limiter.limit("30/minute")
async def decide_escalation(tracking_id: str, request: Request):
    set_correlation_id(tracking_id)
    return await invoke(APPROVAL_AGENT_APP_ID, f"escalations/{tracking_id}/decide", request)


@app.post("/escalations/{tracking_id}/info")
@limiter.limit("30/minute")
async def provide_escalation_info(tracking_id: str, request: Request):
    set_correlation_id(tracking_id)
    return await invoke(APPROVAL_AGENT_APP_ID, f"escalations/{tracking_id}/info", request)


@app.get("/status/{tracking_id}")
@limiter.limit("120/minute")
async def get_status(tracking_id: str, request: Request):
    set_correlation_id(tracking_id)
    return await invoke(APPROVAL_AGENT_APP_ID, f"status/{tracking_id}", request)


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
