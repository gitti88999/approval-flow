from unittest.mock import patch

import pytest

from services.approval_agent import llm_providers
from services.approval_agent.llm_providers import GroqProvider, LLMProviderError, StubProvider, get_provider


def test_stub_provider_returns_deterministic_approval():
    result = StubProvider().evaluate("system prompt", {"total": 42})
    assert result["recommendation"] == "approve"
    assert 0.0 <= result["confidence"] <= 1.0


def test_get_provider_defaults_to_groq(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    assert isinstance(get_provider(), GroqProvider)


def test_get_provider_returns_stub_when_configured(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "stub")
    assert isinstance(get_provider(), StubProvider)


def test_get_provider_rejects_unknown_provider(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "not-a-real-provider")
    with pytest.raises(LLMProviderError):
        get_provider()


def test_groq_provider_raises_llm_provider_error_when_secret_unavailable():
    with patch.object(
        llm_providers.secrets_client, "fetch_secret", side_effect=Exception("no secret store reachable")
    ):
        with pytest.raises(LLMProviderError):
            GroqProvider().evaluate("system prompt", {"total": 42})
