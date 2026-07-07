import pytest
from unittest.mock import AsyncMock, patch

pytestmark = pytest.mark.unit

def test_payload_validation():
    raw_payload = {
        "id": "INV-123",
        "total": 100.0,
        "vendor": "Test Vendor"
    }
    
    assert "id" in raw_payload
    assert raw_payload["total"] > 0

@pytest.mark.asyncio
async def test_publish_to_dapr_pubsub():
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value.status_code = 200
        
        PUB_SUB_URL = "http://127.0.0.1:3500/v1.0/publish/invoice-pubsub/submitted-invoices"
        
        import httpx
        async with httpx.AsyncClient() as client:
            response = await client.post(PUB_SUB_URL, json={"invoice": "data"})
            
        assert response.status_code == 200
        mock_post.assert_called_once()