import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    dapr_http_host: str = os.getenv("DAPR_HTTP_HOST", "approval-agent-dapr")
    dapr_http_port: str = os.getenv("DAPR_HTTP_PORT", "3500")
    dapr_config_store: str = "configstore"

settings = Settings()