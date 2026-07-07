import pytest
from unittest.mock import patch
from services.approval_agent.agent import process_invoice_evaluation

pytestmark = pytest.mark.integration

MOCK_POLICY = {
    "autonomy_settings": {
        "ceiling_usd": 250,
        "confidence_threshold": 0.80,
        "hard_stops": ["GLOBAL-VENDOR", "GLOBAL-FX", "GLOBAL-MATH", "GLOBAL-FRAUD", "GLOBAL-RECEIPT"]
    },
    "rules": {"test": "rules"}
}

@patch('services.approval_agent.agent.load_policy', return_value=MOCK_POLICY)
def test_hard_stops(mock_load):
    invoice_expensive = {"total": 500, "category": "MEAL", "receiptPresent": True, "vendorKnown": True, "lineItems": [{"unitPrice": 500, "quantity": 1}]}
    result = process_invoice_evaluation(invoice_expensive, "T1")
    assert result["recommendation"] == "human_review"
    assert "exceeds autonomy ceiling" in result["reason"]

    invoice_no_receipt = {"total": 50, "category": "MEAL", "receiptPresent": False}
    result = process_invoice_evaluation(invoice_no_receipt, "T2")
    assert result["recommendation"] == "human_review"
    assert "Hard Stop" in result["reason"]
    assert "Missing mandatory receipt" in result["reason"]

    invoice_ok = {"total": 50, "category": "MEAL", "receiptPresent": True, "vendorKnown": True, "lineItems": [{"unitPrice": 50, "quantity": 1}]}
    result = process_invoice_evaluation(invoice_ok, "T3")
    assert result["recommendation"] != "human_review" or "API" in result["reason"]
