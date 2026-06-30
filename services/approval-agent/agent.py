import os
import json
import logging
import httpx  
from groq import Groq

logger = logging.getLogger(__name__)

POLICY_PATH = "/app/policy.md"

def load_policy():
    if not os.path.exists(POLICY_PATH):
        logger.error(f"Critical configuration failure: {POLICY_PATH} not found.")
        return "No specific policy available. Fallback to strict human review."
    with open(POLICY_PATH, "r", encoding="utf-8") as f:
        return f.read()

def process_invoice_evaluation(invoice: dict, tracking_id: str) -> dict:
    logger.info(f"[Agent] Starting LLM analysis for TrackingID: {tracking_id} using Llama-3.3")
    
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        logger.error("[Agent] GROQ_API_KEY missing from environment variables!")
        return {"recommendation": "human_review", "reason": "AI Service unavailable due to missing API Key configuration."}
    
    policy_content = load_policy()
    
    system_prompt = f"""
    You are an automated corporate financial compliance officer. Your job is to evaluate incoming expense invoices against the company's official business policies provided below.
    
    ### COMPANY POLICY:
    {policy_content}
    
    ### Task:
    Analyze the invoice data and provide a clear budget and compliance decision.
    You must output exactly a valid JSON object with two keys:
    1. "recommendation": Must be one of these exact strings: "approve", "reject", or "human_review".
    2. "reason": A brief, accurate explanation in English detailing which policy rules applied or were breached.
    
    Do not include any thinking text, markdown code blocks (like ```json), or prose. Return ONLY the raw JSON object.
    """
    
    user_prompt = f"Invoice Data to Evaluate:\n{json.dumps(invoice, indent=2)}"
    
    try:
        http_client = httpx.Client(trust_env=False)
        
        client = Groq(api_key=api_key, http_client=http_client)
        
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format={"type": "json_object"}, 
            temperature=0.1,
            max_tokens=500
        )
        
        response_text = completion.choices[0].message.content.strip()
        logger.info(f"[Agent LLM Raw Response]: {response_text}")
        
        if response_text.startswith("```"):
            lines = response_text.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            response_text = "\n".join(lines).strip()
            
        result = json.loads(response_text)
        return result
        
    except Exception as e:
        logger.error(f"[Agent LLM Error] Failed evaluating via Groq: {str(e)}")
        return {
            "recommendation": "human_review",
            "reason": f"Internal agent evaluation error: {str(e)}"
        }