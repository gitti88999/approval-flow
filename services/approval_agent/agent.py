import os
import json
import logging
import httpx
from groq import Groq
import requests

# Handle both: running as module (Docker: CWD = service dir) and running from repo root (tests)
try:
    from .config import settings
except ImportError:
    from config import settings

logger = logging.getLogger(__name__)

def validate_hard_stops(invoice: dict, policy: dict) -> str | None:
    hard_stops = policy.get("autonomy_settings", {}).get("hard_stops", [])

    # 1. Receipt presence (hard binary signal)
    if "GLOBAL-RECEIPT" in hard_stops:
        if not invoice.get("receiptPresent", False):
            return "GLOBAL-RECEIPT violation"

    # 2. Vendor trust (binary signal)
    if "GLOBAL-VENDOR" in hard_stops:
        if not invoice.get("vendorKnown", False):
            return "GLOBAL-VENDOR violation"

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
    
def process_invoice_evaluation(invoice: dict, tracking_id: str) -> dict:
    logger.info(f"[Agent] Starting evaluation for TrackingID: {tracking_id}")
    
    # 1. Load Policy (Single point)
    policy = load_policy()
    if not policy:
        return {"recommendation": "human_review", "reason": "Policy configuration missing."}
    
    # 2. Hard Stops Validation
    hard_stop_error = validate_hard_stops(invoice, policy)
    if hard_stop_error:
        logger.info(f"[Agent] Hard stop triggered: {hard_stop_error}")
        return {"recommendation": "human_review", "reason": f"Hard Stop: {hard_stop_error}"}
    
    # 3. Autonomy Ceiling Check
    amount = invoice.get("total", 0)
    ceiling = policy.get("autonomy_settings", {}).get("ceiling_usd", 250)
    if amount > ceiling:
        return {"recommendation": "human_review", "reason": f"Amount {amount} exceeds autonomy ceiling of {ceiling}."}

    # 4. LLM Preparation
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return {"recommendation": "human_review", "reason": "AI Service unavailable: Missing API Key."}
    
    rules_text = json.dumps(policy.get("rules", {}), indent=2)
    system_prompt = f"""
    You are an automated corporate financial compliance officer.
    Evaluate the invoice against the following rules:
    {rules_text}
    
    Output a valid JSON object with:
    1. "recommendation": "approve", "reject", or "human_review".
    2. "reason": Brief explanation of the policy rule applied.
    Return ONLY the raw JSON object.
    """
    
    # 5. AI Evaluation
    try:
        http_client = httpx.Client(trust_env=False)
        client = Groq(api_key=api_key, http_client=http_client)
        
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Invoice Data:\n{json.dumps(invoice, indent=2)}"}
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=500
        )
        
        result = json.loads(completion.choices[0].message.content.strip())
        
        # Post-AI Guardrail
        if result.get("recommendation") == "approve" and amount > ceiling:
            return {"recommendation": "human_review", "reason": "Guardrail violation: AI exceeded manual threshold."}
        
        # recommendation = result.get('recommendation', 'unknown')
        # reason = result.get('reason', 'no reason provided')
        # # logger.info(f"[Agent Evaluation Complete] TrackingID: {tracking_id} | Recommendation: {result.get('recommendation')}")
        # # return result
        # logger.info(f"\n{'='*60}\n📢 DECISION: HUMAN_REVIEW (HARD STOP)\n🆔 TrackingID: {tracking_id}\n🚫 Reason: {reason}\n{'='*60}")        
        # return result
        recommendation = result.get('recommendation', 'unknown').upper()
        reason = result.get('reason', 'no reason provided')
        
        # בניית באנר דינמי לפי התוצאה
        emoji = "✅" if recommendation == "APPROVE" else "⚠️"
        
        banner = (
            f"\n{'='*60}\n"
            f"{emoji} DECISION: {recommendation}\n"
            f"🆔 TrackingID: {tracking_id}\n"
            f"📝 Reason: {reason}\n"
            f"{'='*60}\n"
        )
        logger.info(banner)
        
        return result
            
    except Exception as e:
        logger.error(f"[Agent LLM Error] Failed evaluating via Groq: {str(e)}")
        return {
            "recommendation": "human_review",
            "reason": f"Internal evaluation error: {str(e)}"
        }
