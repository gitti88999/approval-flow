import requests

try:
    from .config import settings
except ImportError:
    from config import settings

SECRET_STORE_NAME = "local-secret-store"


class SecretFetchError(Exception):
    """Raised when a secret cannot be retrieved from the Dapr secret store — callers must treat
    this as a hard failure, never fall back to a default silently."""


def fetch_secret(secret_name: str) -> str:
    url = f"http://{settings.dapr_http_host}:{settings.dapr_http_port}/v1.0/secrets/{SECRET_STORE_NAME}/{secret_name}"
    try:
        response = requests.get(url, timeout=5)
    except requests.exceptions.RequestException as e:
        raise SecretFetchError(f"Failed to reach Dapr secret store for '{secret_name}': {e}") from e

    if response.status_code != 200:
        raise SecretFetchError(f"Dapr secret store returned {response.status_code} for '{secret_name}'")

    data = response.json()
    value = data.get(secret_name)
    if not value:
        raise SecretFetchError(f"Secret '{secret_name}' missing from Dapr secret store response")
    return value
