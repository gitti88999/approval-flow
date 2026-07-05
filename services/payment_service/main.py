import logging
import os
from fastapi import FastAPI, HTTPException, Request, status
import uvicorn

try:
    from . import dapr_client
    from .logging_setup import configure_logging, set_correlation_id
except ImportError:
    import dapr_client
    from logging_setup import configure_logging, set_correlation_id

configure_logging("payment-service")
logger = logging.getLogger(__name__)

app = FastAPI(title="Payment Service", version="1.0")

TERMINAL_STATES = {"paid", "compensated"}

# Lets fixtures/tests force a gateway decline deterministically, since there's no real
# payment gateway to fail against — put this marker in the invoice notes.
FAILURE_MARKER = "SIMULATE_PAYMENT_FAILURE"


def charge_payment(invoice: dict) -> None:
    """Simulated payment gateway call. Raises to signal a declined charge."""
    if FAILURE_MARKER in (invoice.get("notes") or ""):
        raise RuntimeError("Payment gateway declined the charge")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/dapr/subscribe")
async def subscribe():
    return []


@app.post("/on-payment-required", status_code=status.HTTP_200_OK)
async def handle_payment(request: Request):
    event_envelope = await request.json()
    event_data = event_envelope.get("data", event_envelope)
    tracking_id = event_data.get("tracking_id", event_envelope.get("id", "UNKNOWN-ID"))
    set_correlation_id(tracking_id)
    invoice = event_data.get("invoice", {})
    amount = invoice.get("total", 0)

    logger.info(f"Payment saga triggered, amount={amount}")

    try:
        existing = dapr_client.get_payment_state(tracking_id)
    except dapr_client.DaprInfrastructureError as e:
        logger.error(f"{tracking_id} - {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

    if existing and existing.get("status") in TERMINAL_STATES:
        logger.info(f"{tracking_id} - Duplicate payment-required event ignored, already {existing['status']}")
        return {"status": "SUCCESS", "note": "already processed"}

    # Step 1: reserve. This must be persisted before we attempt the charge, and it must
    # never be left in "reserved" once the saga concludes — success commits it to "paid",
    # failure below compensates it to "compensated".
    try:
        dapr_client.save_payment_state(
            tracking_id, {"status": "reserved", "amount": amount, "tracking_id": tracking_id}
        )
    except dapr_client.DaprInfrastructureError as e:
        logger.error(f"{tracking_id} - Failed to record reservation: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

    # Step 2: attempt the charge.
    try:
        charge_payment(invoice)
    except Exception as e:
        logger.warning(f"{tracking_id} - Charge failed ({e}), compensating reservation")
        try:
            dapr_client.save_payment_state(
                tracking_id,
                {"status": "compensated", "amount": amount, "tracking_id": tracking_id, "reason": str(e)},
            )
        except dapr_client.DaprInfrastructureError as state_err:
            logger.error(f"{tracking_id} - Failed to persist compensation, retrying via redelivery: {state_err}")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(state_err))

        dapr_client.publish_outcome(tracking_id, "failed", str(e))
        return {"status": "SUCCESS", "outcome": "failed"}

    # Step 3: commit.
    try:
        dapr_client.save_payment_state(
            tracking_id, {"status": "paid", "amount": amount, "tracking_id": tracking_id}
        )
    except dapr_client.DaprInfrastructureError as e:
        logger.error(f"{tracking_id} - Failed to persist paid state after a successful charge: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

    dapr_client.publish_outcome(tracking_id, "paid", "Payment completed successfully")
    logger.info(f"{tracking_id} - Payment completed successfully")
    return {"status": "SUCCESS", "outcome": "paid"}


if __name__ == "__main__":
    port = int(os.getenv("APP_PORT", 8002))
    uvicorn.run(app, host="0.0.0.0", port=port)
