import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # ה-Host בתוך ה-network של ה-docker הוא שם השירות של ה-sidecar
    dapr_http_host: str = os.getenv("DAPR_HTTP_HOST", "approval-agent-dapr")
    dapr_http_port: str = os.getenv("DAPR_HTTP_PORT", "3500")
    dapr_config_store: str = "configstore"

settings = Settings()
# DAPR_STORE_NAME = "statestore" 
# DAPR_CONFIG_STORE = "configstore"
# DAPR_HOST = os.getenv("DAPR_RUNTIME_HOST", "approval-agent-dapr")
# DAPR_HTTP_PORT = os.getenv("DAPR_HTTP_PORT", "3500")
# DAPR_STATE_URL = f"http://127.0.0.1:3501/v1.0/state/{DAPR_STORE_NAME}"
# DAPR_CONFIG_URL = f"http://{DAPR_HOST}:{DAPR_HTTP_PORT}/v1.0/configuration/{DAPR_CONFIG_STORE}"