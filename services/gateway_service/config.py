import os

DAPR_HOST = os.getenv("DAPR_RUNTIME_HOST", "gateway-dapr")
DAPR_HTTP_PORT = os.getenv("DAPR_HTTP_PORT", "3500")
DAPR_INVOKE_BASE_URL = f"http://{DAPR_HOST}:{DAPR_HTTP_PORT}/v1.0/invoke"

INGESTION_APP_ID = os.getenv("INGESTION_APP_ID", "ingestion_service")
APPROVAL_AGENT_APP_ID = os.getenv("APPROVAL_AGENT_APP_ID", "approval-agent")
