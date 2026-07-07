from unittest.mock import MagicMock, patch

import pytest

from services.approval_agent import secrets_client

pytestmark = pytest.mark.unit


def test_fetch_secret_returns_value_on_success():
    response = MagicMock(status_code=200)
    response.json.return_value = {"GROQ_API_KEY": "sk-test-123"}
    with patch.object(secrets_client.requests, "get", return_value=response):
        assert secrets_client.fetch_secret("GROQ_API_KEY") == "sk-test-123"


def test_fetch_secret_raises_on_non_200():
    response = MagicMock(status_code=404)
    with patch.object(secrets_client.requests, "get", return_value=response):
        with pytest.raises(secrets_client.SecretFetchError):
            secrets_client.fetch_secret("GROQ_API_KEY")


def test_fetch_secret_raises_when_value_missing():
    response = MagicMock(status_code=200)
    response.json.return_value = {}
    with patch.object(secrets_client.requests, "get", return_value=response):
        with pytest.raises(secrets_client.SecretFetchError):
            secrets_client.fetch_secret("GROQ_API_KEY")


def test_fetch_secret_raises_on_connection_error():
    import requests as requests_module

    with patch.object(secrets_client.requests, "get", side_effect=requests_module.exceptions.ConnectionError("boom")):
        with pytest.raises(secrets_client.SecretFetchError):
            secrets_client.fetch_secret("GROQ_API_KEY")
