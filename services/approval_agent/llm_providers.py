import json
import logging
import os
from abc import ABC, abstractmethod

import httpx
from groq import Groq

try:
    from . import secrets_client
except ImportError:
    import secrets_client

logger = logging.getLogger(__name__)


class LLMProviderError(Exception):
    """Raised when a provider cannot produce an evaluation. The router treats this as a hard
    failure and escalates to human review — it never guesses on the provider's behalf."""


class LLMProvider(ABC):
    @abstractmethod
    def evaluate(self, system_prompt: str, invoice: dict) -> dict:
        """Returns a dict with 'recommendation', 'reason', and 'confidence'."""


class GroqProvider(LLMProvider):
    def __init__(self, model: str = "llama-3.3-70b-versatile"):
        self.model = model

    def evaluate(self, system_prompt: str, invoice: dict) -> dict:
        try:
            api_key = secrets_client.fetch_secret("GROQ_API_KEY")
            http_client = httpx.Client(trust_env=False)
            client = Groq(api_key=api_key, http_client=http_client)
            completion = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Invoice Data:\n{json.dumps(invoice, indent=2)}"},
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
                max_tokens=500,
            )
            return json.loads(completion.choices[0].message.content.strip())
        except Exception as e:
            raise LLMProviderError(f"Groq provider failed: {e}") from e


class StubProvider(LLMProvider):
    """Deterministic, offline provider — no network calls, no API key required. Used for CI and
    local development, per the assignment's guidance to use a stubbed/local model to avoid
    rate limits. By the time a provider is invoked, the router has already confirmed the amount
    is within the autonomy ceiling, so a simple constant response is enough to exercise the rest
    of the pipeline deterministically."""

    def evaluate(self, system_prompt: str, invoice: dict) -> dict:
        return {
            "recommendation": "approve",
            "reason": "Stub provider: within policy limits (no live LLM configured).",
            "confidence": 0.95,
        }


def get_provider() -> LLMProvider:
    provider_name = os.getenv("LLM_PROVIDER", "groq").lower()
    if provider_name == "stub":
        return StubProvider()
    if provider_name == "groq":
        return GroqProvider()
    raise LLMProviderError(f"Unknown LLM_PROVIDER '{provider_name}'")
