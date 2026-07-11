"""Eval harness: scores the approval-agent's decisions against a labeled set of invoices.

Runs `process_invoice_evaluation` in-process against the real `config/policy.json` — no live
stack needed — and reports per-class precision/recall plus a confusion matrix over the two
outcomes that actually matter downstream (`approve` triggers payment; anything else, including an
LLM's "reject", routes to the same human escalation queue — see `main.py`'s
`recommendation == "approve"` check).

Cases split into two groups:
  - Deterministic (hard stops, autonomy ceiling): enforced by code before the LLM is ever called,
    so any provider gets these right by construction. Included to make the harness's own
    scoring machinery verifiable — a broken harness should get 0 %, not a broken agent.
  - Judgment: within the ceiling, no hard stop, decided by the LLM against the retrieved policy
    text — this is the part actually worth measuring. StubProvider always says "approve", so
    running with LLM_PROVIDER=stub will visibly fail every judgment case labeled human_review —
    that's expected, and is itself the harness proving it can tell a bad provider from a good one.
    Run with LLM_PROVIDER=groq for a meaningful score.

Usage:
    LLM_PROVIDER=groq python scripts/eval_harness.py
    LLM_PROVIDER=stub python scripts/eval_harness.py   # sanity-checks the harness itself
"""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "services" / "approval_agent"))

from unittest.mock import patch  # noqa: E402

import agent  # noqa: E402

POLICY = {
    "autonomy_settings": {
        "ceiling_usd": 250,
        "confidence_threshold": 0.80,
        "hard_stops": ["GLOBAL-VENDOR", "GLOBAL-FX", "GLOBAL-MATH", "GLOBAL-FRAUD", "GLOBAL-RECEIPT"],
    },
    "rules": {
        "MEAL-01": {
            "limit": 75,
            "fields": ["attendee_count"],
            "description": "Personal/team meals reimbursable up to $75/attendee. Missing attendee count = missing info.",
        },
        "MEAL-02": {
            "limit": 500,
            "fields": ["business_justification", "client_name"],
            "description": "Client entertainment over $500 requires business justification and client name.",
        },
        "MEAL-03": {"reimbursable": False, "description": "Alcohol-only receipts are not reimbursable."},
        "TRAVEL-01": {"description": "Economy flights, standard hotels, and standard/economy ground transport are eligible."},
        "TRAVEL-02": {"limit": 1500, "action": "human_approval", "description": "Travel over $1,500 requires manager approval."},
        "TRAVEL-03": {"action": "human_approval", "description": "First/business-class travel always requires approval."},
        "SAAS-01": {"limit": 200, "description": "Subscriptions are policy-eligible up to $200 / month."},
        "HW-01": {"limit": 1000, "description": "Hardware purchases are policy-eligible up to $1,000."},
        "HW-02": {"limit": 1000, "action": "human_approval", "description": "Hardware over $1,000 is a Capital expense — always human-approved."},
    },
}


def _invoice(total, category, description, notes=None, receipt=True, vendor_known=True, attendees=1):
    return {
        "id": f"EVAL-{category}-{total}",
        "total": total,
        "category": category,
        "receiptPresent": receipt,
        "vendorKnown": vendor_known,
        "attendees": attendees,
        "lineItems": [{"description": description, "unitPrice": total, "quantity": 1}],
        "taxAmount": 0,
        "notes": notes,
    }


# (name, invoice, expected_recommendation, group)
CASES = [
    # -- Deterministic: enforced in code before the LLM is ever asked --
    ("missing receipt is a hard stop", _invoice(50, "meals", "lunch", receipt=False), "human_review", "deterministic"),
    ("unknown vendor is a hard stop", _invoice(50, "meals", "lunch", vendor_known=False), "human_review", "deterministic"),
    ("amount over the autonomy ceiling", _invoice(9000, "hardware", "laptop"), "human_review", "deterministic"),
    ("small in-policy meal is auto-approved", _invoice(20, "meals", "team lunch", attendees=2), "approve", "deterministic"),

    # -- Judgment: within ceiling, no hard stop — the LLM decides against the retrieved policy --
    ("meal under the $75/attendee limit", _invoice(60, "meals", "client lunch", attendees=1), "approve", "judgment"),
    ("meal over the $75/attendee limit", _invoice(200, "meals", "team dinner", attendees=1), "human_review", "judgment"),
    ("alcohol-only receipt is never reimbursable", _invoice(45, "meals", "bar tab, drinks only"), "human_review", "judgment"),
    ("saas subscription under the $200 limit", _invoice(49, "saas", "monthly subscription"), "approve", "judgment"),
    ("saas subscription over the $200 limit", _invoice(240, "saas", "annual plan billed monthly"), "human_review", "judgment"),
    ("hardware under the $1,000 limit", _invoice(150, "hardware", "keyboard and mouse"), "approve", "judgment"),
    ("economy travel is eligible", _invoice(180, "travel", "economy flight"), "approve", "judgment"),
    ("first-class travel always needs approval", _invoice(220, "travel", "first-class upgrade"), "human_review", "judgment"),
]


def run():
    provider_name = agent.llm_providers.get_provider().__class__.__name__
    print(f"Provider: {provider_name}\n")

    # GroqProvider fetches its API key through the Dapr sidecar (M5 — never a plain env var in
    # application code), which isn't reachable when this script runs outside the compose network.
    # This is a dev-tool-only bypass at that one boundary, same as the unit tests do; application
    # code itself is never changed.
    secret_patch = patch.object(
        agent.llm_providers.secrets_client, "fetch_secret", return_value=os.environ.get("GROQ_API_KEY", "")
    )

    # A brief pause between calls avoids tripping the free-tier rate limit when hitting a real
    # LLM provider back-to-back; irrelevant (and skipped) for the offline stub provider.
    inter_call_delay = 1.5 if provider_name == "GroqProvider" else 0

    rows = []
    with patch.object(agent, "load_policy", return_value=POLICY), secret_patch:
        for i, (name, invoice, expected, group) in enumerate(CASES):
            if i > 0 and inter_call_delay:
                time.sleep(inter_call_delay)
            result = agent.process_invoice_evaluation(invoice, f"EVAL-{name}")
            actual = result["recommendation"]
            # Downstream, only "approve" is distinct from everything else (main.py routes
            # anything that isn't literally "approve" — including an LLM's "reject" — to the
            # same human escalation queue), so normalize on that boundary.
            actual_bucket = "approve" if actual == "approve" else "human_review"
            correct = actual_bucket == expected
            rows.append((name, group, expected, actual, correct))

    print(f"{'case':<45} {'group':<13} {'expected':<13} {'actual':<13} result")
    print("-" * 95)
    for name, group, expected, actual, correct in rows:
        mark = "OK" if correct else "MISS"
        print(f"{name:<45} {group:<13} {expected:<13} {actual:<13} {mark}")

    total = len(rows)
    correct_count = sum(1 for *_r, correct in rows if correct)
    print(f"\nOverall: {correct_count}/{total} correct ({100 * correct_count / total:.0f}%)")

    for group in ("deterministic", "judgment"):
        group_rows = [r for r in rows if r[1] == group]
        group_correct = sum(1 for r in group_rows if r[4])
        print(f"  {group}: {group_correct}/{len(group_rows)}")

    approve_rows = [r for r in rows if r[2] == "approve"]
    approve_tp = sum(1 for r in approve_rows if r[4])
    predicted_approve = [r for r in rows if r[3] == "approve"]
    predicted_approve_correct = sum(1 for r in predicted_approve if r[2] == "approve")
    if approve_rows:
        print(f"\nRecall on 'approve' (of {len(approve_rows)} that should approve, how many did): "
              f"{approve_tp}/{len(approve_rows)}")
    if predicted_approve:
        print(f"Precision on 'approve' (of {len(predicted_approve)} it approved, how many should have): "
              f"{predicted_approve_correct}/{len(predicted_approve)}")

    return 0 if correct_count == total else 1


if __name__ == "__main__":
    sys.exit(run())
