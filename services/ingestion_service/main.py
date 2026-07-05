import uuid
import logging
from fastapi import FastAPI, BackgroundTasks, status, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from schemas import InvoiceSubmission
import dapr_client
from logging_setup import configure_logging, set_correlation_id

configure_logging("ingestion-service")
logger = logging.getLogger(__name__)

# Initialize the global rate limiter using the client's remote IP address
limiter = Limiter(key_func=get_remote_address)

app = FastAPI(title="Ingestion Service", version="1.0")

# Attach the limiter state and custom exception handler to the FastAPI application context
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Enable global CORS handling for local developer environments
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Apply strict request limits to block brute-force or faulty client loops
@app.post("/submit", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("60/minute")  # Restricts each unique IP identifier to 60 executions per minute
async def submit_invoice(invoice: InvoiceSubmission, background_tasks: BackgroundTasks, request: Request):
    # Note: The 'request' object must be injected so slowapi can extract connection routing metadata
    tracking_id = str(uuid.uuid4())
    set_correlation_id(tracking_id)
    logger.info(f"Processing ingestion for invoice id: {invoice.id}")
    
    # Generate unique business transaction fingerprint
    idempotency_key = f"dup-{invoice.vendor}-{invoice.invoiceNumber}-{invoice.total}"
    
    # 1. Execute GLOBAL-DUP pipeline check
    try:
        if dapr_client.check_global_duplicate(idempotency_key, tracking_id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="GLOBAL-DUP: Invoice signature has already been processed."
            )
    except dapr_client.DaprInfrastructureError as err:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(err)
        )
    
    # 2. Persist the transaction fingerprint key (must succeed before publishing)
    if not dapr_client.save_idempotency_state(idempotency_key, invoice.id, tracking_id):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to persist idempotency key — cannot guarantee deduplication."
        )
    
    # 3. Queue the event asynchronously using standard Background Tasks
    logger.info(f"Adding publish task for tracking_id: {tracking_id}")
    background_tasks.add_task(dapr_client.publish_to_pubsub, tracking_id, invoice)
    return {
        "status": "Accepted",
        "tracking_id": tracking_id,
        "message": "Invoice safely ingested and registered for validation rules workflow."
    }
@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/dapr/subscribe")
async def subscribe():
    return []
if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=False)
