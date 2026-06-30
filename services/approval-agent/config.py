import os

DAPR_STORE_NAME = "statestore" 
DAPR_HOST = "127.0.0.1" 
DAPR_HTTP_PORT = os.getenv("DAPR_HTTP_PORT", "3501")
DAPR_STATE_URL = f"http://127.0.0.1:3501/v1.0/state/{DAPR_STORE_NAME}"