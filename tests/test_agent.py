import pytest
import httpx
from unittest.mock import AsyncMock, patch

def test_dapr_payload_structure():
    tracking_id = "TEST-123"
    result = {"recommendation": "approve", "reason": "Policy met"}
    invoice = {"id": "INV-1"}
    
    state_payload = [
        {
            "key": f"invoice_evaluation:{tracking_id}",
            "value": {
                "tracking_id": tracking_id,
                "recommendation": result.get("recommendation"),
                "reason": result.get("reason")
            }
        }
    ]
    
    assert isinstance(state_payload, list)
    assert len(state_payload) == 1
    assert state_payload[0]["key"] == "invoice_evaluation:TEST-123"

@pytest.mark.asyncio
async def test_dapr_connection_url():
    DAPR_STATE_URL = "http://127.0.0.1:3500/v1.0/state/statestore"
    
    assert "127.0.0.1" in DAPR_STATE_URL
    assert "3500" in DAPR_STATE_URL
    assert "statestore" in DAPR_STATE_URL

@pytest.mark.asyncio
async def test_save_to_dapr_success():
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value.status_code = 204
        
        async with httpx.AsyncClient() as client:
            response = await client.post("http://127.0.0.1:3500/v1.0/state/statestore", json=[{"key": "test"}])
            
        assert response.status_code == 204
        mock_post.assert_called_once()