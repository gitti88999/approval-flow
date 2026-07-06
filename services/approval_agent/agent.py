import json
import logging
import requests

try:
    from .config import settings
    from . import llm_providers, tracing_setup
except ImportError:
    from config import settings
    import llm_providers
    import tracing_setup

logger = logging.getLogger(__name__)

def validate_hard_stops(invoice: dict, policy: dict) -> str | None:
    hard_stops = policy.get("autonomy_settings", {}).get("hard_stops", [])

    # 1. Receipt presence (hard binary signal)
    if "GLOBAL-RECEIPT" in hard_stops:
        if not invoice.get("receiptPresent", False):
            return "Missing mandatory receipt (GLOBAL-RECEIPT)"

    # 2. Vendor trust (binary signal)
    if "GLOBAL-VENDOR" in hard_stops:
        if not invoice.get("vendorKnown", False):
            return "Unknown/unapproved vendor (GLOBAL-VENDOR)"

    # 3. Math integrity (strict structural check only)
    if "GLOBAL-MATH" in hard_stops:
        line_items = invoice.get("lineItems", [])

        subtotal = sum(
            item.get("unitPrice", 0) * item.get("quantity", 0)
            for item in line_items
        )

        tax = invoice.get("taxAmount", 0)

        expected = subtotal + tax
        actual = invoice.get("total", 0)

        if abs(expected - actual) > 0.01:
            return f"GLOBAL-MATH violation (expected={expected:.2f}, actual={actual:.2f})"

    return None

def load_policy():
    """Fetches the policy from the Dapr Configuration Store."""
    url = f"http://{settings.dapr_http_host}:{settings.dapr_http_port}/v1.0/configuration/configstore"
    params = {'keys': 'policy_rules'}
    
    try:
        response = requests.get(url, params=params, timeout=5)

        logger.info(f"Status: {response.status_code}")
        logger.info(f"Body: {response.text}")

        if response.status_code != 200:
            logger.warning(f"[Agent] Failed to load policy, HTTP {response.status_code}, using default fallback.")
            return {"min_amount": 0, "max_amount": 500, "auto_approve": True, "autonomy_settings": {"ceiling_usd": 250}}

        data = response.json()

        # The Dapr Configuration API may wrap items in an "items" key or
        # return them directly at the top level. Iterate to find the entry
        # that contains our configuration value.
        config_entries = data.get("items", data)

        for key, entry in config_entries.items():
            if isinstance(entry, dict) and "value" in entry:
                policy_raw = entry["value"]
                parsed = json.loads(policy_raw)
                if isinstance(parsed, dict) and "autonomy_settings" in parsed and "rules" in parsed:
                    logger.info(f"[Agent] Policy loaded successfully from key: {key}")
                    return parsed

        logger.warning("[Agent] Policy configuration not found in successful response, using default fallback.")
    except Exception:
        logger.exception("[Agent] Exception while loading policy")
            
    logger.warning("[Agent] Failed to load policy, using default fallback.")
    return {"min_amount": 0, "max_amount": 500, "auto_approve": True, "autonomy_settings": {"ceiling_usd": 250}}

def log_decision(tracking_id, decision, reason):
    agent_name = "approval-agent-1"
    separator = "=" * 60
    emoji = "✅" if decision == "APPROVE" else "⚠️"
    
    banner = (
        f"\n{agent_name:<25} | {emoji} DECISION: {decision}\n"
        f"{agent_name:<25} | 🆔 TrackingID: {tracking_id}\n"
        f"{agent_name:<25} | 📝 Reason: {reason}\n"
        f"{agent_name:<25} | {separator}"
    )
    logger.info(banner)

def process_invoice_evaluation(invoice: dict, tracking_id: str) -> dict:
    logger.info(f"[Agent] Starting evaluation for TrackingID: {tracking_id}")

    policy = load_policy()
    if not policy:
        return {"recommendation": "human_review", "reason": "Policy configuration missing.", "confidence": 0.0}

    # 2. Hard Stops Validation
    hard_stop_error = validate_hard_stops(invoice, policy)
    if hard_stop_error:
        log_decision(tracking_id, "REJECT", f"Hard Stop: {hard_stop_error}")
        return {"recommendation": "human_review", "reason": f"Hard Stop: {hard_stop_error}", "confidence": 1.0}

    # 3. Autonomy Ceiling Check
    amount = invoice.get("total", 0)
    ceiling = policy.get("autonomy_settings", {}).get("ceiling_usd", 250)
    if amount > ceiling:
        log_decision(tracking_id, "REJECT", f"Amount {amount} exceeds autonomy ceiling of {ceiling}.")
        return {
            "recommendation": "human_review",
            "reason": f"Amount {amount} exceeds autonomy ceiling of {ceiling}.",
            "confidence": 1.0,
        }
    # 4. LLM Preparation
    rules_text = json.dumps(policy.get("rules", {}), indent=2)
    system_prompt = f"""
    You are an automated corporate financial compliance officer.
    Evaluate the invoice against the following rules:
    {rules_text}

    Output a valid JSON object with:
    1. "recommendation": "approve", "reject", or "human_review".
    2. "reason": Brief explanation of the policy rule applied.
    3. "confidence": a number between 0.0 and 1.0 expressing how confident you are in this recommendation.
    Return ONLY the raw JSON object.
    """

    # 5. AI Evaluation — provider is swappable via LLM_PROVIDER (groq default, stub for CI/offline)
    try:
        provider = llm_providers.get_provider()
        tracer = tracing_setup.get_tracer()
        # N4 — nests under whatever span is currently active (handle_invoice_submission, set up
        # by main.py), so the LLM call shows up as part of the same end-to-end trace.
        with tracer.start_as_current_span("llm.evaluate") as span:
            span.set_attribute("correlation_id", tracking_id)
            span.set_attribute("llm.provider", provider.__class__.__name__)
            result = provider.evaluate(system_prompt, invoice)
            span.set_attribute("llm.recommendation", str(result.get("recommendation")))

        recommendation = result.get('recommendation', 'unknown').lower()
        reason = result.get('reason', 'no reason provided')
        try:
            confidence = float(result.get("confidence", 0.0) or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        confidence_threshold = policy.get("autonomy_settings", {}).get("confidence_threshold", 0.8)

        # Post-AI Guardrails: the LLM only recommends, the router has the final say.
        if recommendation == "approve" and amount > ceiling:
            recommendation = "human_review"
            reason = "Guardrail violation: AI exceeded manual threshold."
        elif recommendation == "approve" and confidence < confidence_threshold:
            recommendation = "human_review"
            reason = f"Guardrail violation: confidence {confidence:.2f} below threshold {confidence_threshold}."

        emoji = "✅" if recommendation == "approve" else "⚠️"

        banner = (
            f"\n{'='*60}\n"
            f"{emoji} DECISION: {recommendation.upper()}\n"
            f"🆔 TrackingID: {tracking_id}\n"
            f"📝 Reason: {reason}\n"
            f"{'='*60}\n"
        )
        logger.info(banner)

        return {"recommendation": recommendation, "reason": reason, "confidence": confidence}

    except Exception as e:
        logger.error(f"[Agent LLM Error] Provider evaluation failed: {str(e)}")
        return {
            "id": tracking_id,
            "recommendation": "human_review",
            "reason": f"Internal evaluation error: {str(e)}",
            "confidence": 0.0,
        }
