import sys
import os
from unittest.mock import MagicMock

# 1. מוודאים שהשורש בנתיב
sys.path.append(os.getcwd())

# 2. לפני ה-import, אנחנו מכינים מוק ל-Dapr
import services.approval_agent.agent as agent

# יוצרים מוק שפשוט מחזיר None כדי שהקוד לא יקרוס
# או שנשנה את הפונקציה load_policy עצמה בזמן ריצה
def mock_load_policy():
    return {
        "autonomy_settings": {
            "ceiling_usd": 1000,
            "supported_categories": ["MEAL"]
        },
        "rules": {"test": "rules"}
    }

# מזריקים את המוק לתוך המודול
agent.load_policy = mock_load_policy

from services.approval_agent.agent import process_invoice_evaluation

# 3. נתוני טסט
invoice = {"total": 50.0, "category": "MEAL"}

print("--- הרצת דמו: approval-agent (הזרקת מוק ידנית) ---")
result = process_invoice_evaluation(invoice, "DEMO-001")
print(f"Result: {result}")