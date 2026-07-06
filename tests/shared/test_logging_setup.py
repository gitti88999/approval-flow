import importlib
import json
import logging

import pytest

MODULES = [
    "services.ingestion_service.logging_setup",
    "services.approval_agent.logging_setup",
    "services.payment_service.logging_setup",
    "services.gateway_service.logging_setup",
]


@pytest.mark.parametrize("module_name", MODULES)
def test_json_formatter_emits_valid_json_with_correlation_id(module_name):
    module = importlib.import_module(module_name)
    module.set_correlation_id("TRK-123")

    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname=__file__, lineno=1,
        msg="hello world", args=(), exc_info=None,
    )
    module.CorrelationIdFilter().filter(record)
    formatted = module.JsonFormatter("some-service").format(record)

    payload = json.loads(formatted)
    assert payload["correlation_id"] == "TRK-123"
    assert payload["service"] == "some-service"
    assert payload["message"] == "hello world"
    assert payload["level"] == "INFO"


@pytest.mark.parametrize("module_name", MODULES)
def test_default_correlation_id_is_placeholder_when_unset(module_name):
    module = importlib.import_module(module_name)
    module.correlation_id_var.set("-")

    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname=__file__, lineno=1,
        msg="no correlation set", args=(), exc_info=None,
    )
    module.CorrelationIdFilter().filter(record)
    assert record.correlation_id == "-"
