from services.approval_agent import policy_rag

POLICY = {
    "autonomy_settings": {"ceiling_usd": 250, "confidence_threshold": 0.80, "hard_stops": []},
    "rules": {
        "MEAL-01": {
            "limit": 75,
            "fields": ["attendee_count"],
            "description": "Personal/team meals reimbursable up to $75/attendee.",
        },
        "MEAL-03": {"reimbursable": False, "description": "Alcohol-only receipts are not reimbursable."},
        "TRAVEL-01": {"description": "Economy flights, standard hotels, and standard ground transport are eligible."},
        "TRAVEL-02": {"limit": 1500, "action": "human_approval", "description": "Travel over $1,500 requires manager approval."},
        "SAAS-01": {"limit": 200, "description": "Subscriptions eligible up to $200/month."},
        "HW-01": {"limit": 1000, "description": "Hardware purchases eligible up to $1,000."},
    },
}


def _invoice(category, description="", notes=None):
    return {
        "category": category,
        "notes": notes,
        "lineItems": [{"description": description, "quantity": 1, "unitPrice": 10.0}],
    }


def test_retrieves_the_matching_category_rules_first():
    invoice = _invoice("meals", "team lunch")
    retrieved = policy_rag.retrieve_relevant_rules(invoice, POLICY, top_k=3)

    ids = [r["rule_id"] for r in retrieved]
    assert ids[0] in {"MEAL-01", "MEAL-03"}
    assert "TRAVEL-01" not in ids[:1]


def test_top_result_scores_higher_than_unrelated_rules():
    invoice = _invoice("saas", "monthly subscription")
    retrieved = policy_rag.retrieve_relevant_rules(invoice, POLICY, top_k=len(POLICY["rules"]))

    scores_by_id = {r["rule_id"]: r["score"] for r in retrieved}
    assert scores_by_id["SAAS-01"] > scores_by_id["HW-01"]


def test_respects_top_k():
    invoice = _invoice("travel", "flight and hotel")
    retrieved = policy_rag.retrieve_relevant_rules(invoice, POLICY, top_k=2)
    assert len(retrieved) == 2


def test_never_returns_empty_even_with_no_vocabulary_overlap():
    invoice = _invoice("xyzzy-unrelated-category", "qwertyuiop")
    retrieved = policy_rag.retrieve_relevant_rules(invoice, POLICY, top_k=3)
    assert len(retrieved) > 0


def test_empty_policy_returns_no_rules():
    invoice = _invoice("meals", "lunch")
    retrieved = policy_rag.retrieve_relevant_rules(invoice, {"rules": {}})
    assert retrieved == []
