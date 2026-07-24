import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from services.approval_agent import agent as agent_module
from services.approval_agent import main as agent_main

pytestmark = pytest.mark.unit


class DummySpan:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def set_attribute(self, *args, **kwargs):
        return None


class DummyTracer:
    def start_as_current_span(self, *args, **kwargs):
        return DummySpan()


def test_subscriber_poison_pill_handling():
    with patch("services.approval_agent.main.agent.process_invoice_evaluation", side_effect=RuntimeError("boom")):
        with patch("services.approval_agent.main.tracer", DummyTracer()):
            client = TestClient(agent_main.app)
            response = client.post(
                "/events/invoice-submissions",
                json={
                    "data": {
                        "tracking_id": "trace-123",
                        "invoice": {"id": "INV-1"},
                    }
                },
            )

    assert response.status_code == 200
    assert response.json() == {"status": "DROP"}


def test_llm_hallucination_fallback():
    policy = {
        "autonomy_settings": {"ceiling_usd": 250, "confidence_threshold": 0.8},
        "rules": {},
    }

    with patch.object(agent_module, "load_policy", return_value=policy):
        with patch.object(agent_module, "validate_hard_stops", return_value=None):
            with patch.object(agent_module.policy_rag, "retrieve_relevant_rules", return_value=[]):
                class FakeProvider:
                    def evaluate(self, system_prompt, invoice):
                        return {"recommendation": 123, "reason": "bad", "confidence": 0.8}

                with patch.object(agent_module.llm_providers, "get_provider", return_value=FakeProvider()):
                    with patch.object(agent_module.tracing_setup, "get_tracer", return_value=DummyTracer()):
                        result = agent_module.process_invoice_evaluation(
                            {"id": "INV-1", "total": 10, "lineItems": []},
                            "trace-456",
                        )

    assert result == {
        "recommendation": "human_review",
        "reason": "Schema validation failed",
        "confidence": 0.0,
    }
