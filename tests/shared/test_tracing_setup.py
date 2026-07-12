import importlib

import pytest

pytestmark = pytest.mark.unit

MODULES = [
    "services.approval_agent.tracing_setup",
    "services.payment_service.tracing_setup",
]

VALID_TRACEPARENT = "00-1b1728fa2316e049dedd399ed711cea5-ecc8598ac26c9f57-01"


@pytest.mark.parametrize("module_name", MODULES)
def test_extract_context_returns_none_for_empty_traceparent(module_name):
    module = importlib.import_module(module_name)
    assert module.extract_context(None) is None
    assert module.extract_context("") is None


@pytest.mark.parametrize("module_name", MODULES)
def test_extract_context_parses_valid_traceparent(module_name):
    module = importlib.import_module(module_name)
    context = module.extract_context(VALID_TRACEPARENT)
    assert context is not None


@pytest.mark.parametrize("module_name", MODULES)
def test_inject_headers_adds_traceparent_key_within_a_span(module_name):
    module = importlib.import_module(module_name)
    module.configure_tracing(f"test-{module_name}")
    tracer = module.get_tracer()
    with tracer.start_as_current_span("test-span"):
        headers = module.inject_headers({"Content-Type": "application/json"})
    assert "traceparent" in headers
    assert headers["Content-Type"] == "application/json"


@pytest.mark.parametrize("module_name", MODULES)
def test_inject_headers_does_not_mutate_input(module_name):
    module = importlib.import_module(module_name)
    original = {"a": "b"}
    module.inject_headers(original)
    assert original == {"a": "b"}
