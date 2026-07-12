import os

DAPR_HOST = os.getenv("DAPR_RUNTIME_HOST", "ingestion-service-dapr")
DAPR_HTTP_PORT = os.getenv("DAPR_HTTP_PORT", "3500")
DAPR_BASE_URL = f"http://{DAPR_HOST}:{DAPR_HTTP_PORT}/v1.0"
DAPR_STATE_URL = f"{DAPR_BASE_URL}/state/statestore"
DAPR_PUBSUB_URL = f"{DAPR_BASE_URL}/publish/invoice-pubsub/submitted-invoices"