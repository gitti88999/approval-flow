import sys
import os
from unittest.mock import MagicMock

sys.path.append(os.getcwd())

import services.approval_agent.agent as agent

def mock_load_policy():
    return {
        "autonomy_settings": {
            "ceiling_usd": 1000,
            "supported_categories": ["MEAL"]
        },
        "rules": {"test": "rules"}
    }

agent.load_policy = mock_load_policy

from services.approval_agent.agent import process_invoice_evaluation

invoice = {"total": 50.0, "category": "MEAL"}

print("--- הרצת דמו: approval-agent (הזרקת מוק ידנית) ---")
result = process_invoice_evaluation(invoice, "DEMO-001")
print(f"Result: {result}")