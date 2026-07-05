import pytest
from unittest.mock import patch
from services.approval_agent.agent import process_invoice_evaluation

# המדיניות שנשתמש בה בטסט
MOCK_POLICY = {
    "autonomy_settings": {
        "ceiling_usd": 250,
        "confidence_threshold": 0.80,
        "hard_stops": ["GLOBAL-VENDOR", "GLOBAL-FX", "GLOBAL-MATH", "GLOBAL-FRAUD", "GLOBAL-RECEIPT"]
    },
    "rules": {"test": "rules"}
}

# שימוש ב-patch כדי להחליף את הפונקציה load_policy בגרסת המוק שלה
@patch('services.approval_agent.agent.load_policy', return_value=MOCK_POLICY)
def test_hard_stops(mock_load):
    # 1. בדיקת סכום חורג (must pass hard stops first)
    invoice_expensive = {"total": 500, "category": "MEAL", "receiptPresent": True, "vendorKnown": True, "lineItems": [{"unitPrice": 500, "quantity": 1}]}
    result = process_invoice_evaluation(invoice_expensive, "T1")
    assert result["recommendation"] == "human_review"
    assert "exceeds autonomy ceiling" in result["reason"]

    # 2. בדיקת Hard Stop — חסר receipt
    invoice_no_receipt = {"total": 50, "category": "MEAL", "receiptPresent": False}
    result = process_invoice_evaluation(invoice_no_receipt, "T2")
    assert result["recommendation"] == "human_review"
    assert "Hard Stop" in result["reason"]
    assert "Missing mandatory receipt" in result["reason"]

    # 3. תרחיש תקין (אמור לעבור את ה-Hard Stops)
    # כאן הוא ינסה להגיע ל-Groq, אז נצפה לשגיאת API או human_review אם אין מפתח
    invoice_ok = {"total": 50, "category": "MEAL", "receiptPresent": True, "vendorKnown": True, "lineItems": [{"unitPrice": 50, "quantity": 1}]}
    result = process_invoice_evaluation(invoice_ok, "T3")
    assert result["recommendation"] != "human_review" or "API" in result["reason"]
