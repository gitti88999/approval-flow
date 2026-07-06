from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Request

from services.gateway_service import main as gateway_main


def _request(method="POST", body=b'{"id":"INV-1"}', content_type="application/json"):
    req = MagicMock(spec=Request)
    req.method = method
    req.body = AsyncMock(return_value=body)
    req.headers = {"content-type": content_type}
    return req


@pytest.mark.asyncio
async def test_invoke_forwards_method_body_and_status():
    downstream = MagicMock(status_code=202, content=b'{"status":"Accepted"}', headers={"content-type": "application/json"})

    with patch("services.gateway_service.main.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.request.return_value = downstream
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        response = await gateway_main.invoke("ingestion_service", "submit", _request())

    assert response.status_code == 202
    call = mock_client.request.call_args
    assert call.args[0] == "POST"
    assert call.args[1].endswith("/v1.0/invoke/ingestion_service/method/submit")
    assert call.kwargs["content"] == b'{"id":"INV-1"}'


@pytest.mark.asyncio
async def test_invoke_raises_502_when_upstream_unreachable():
    import httpx
    from fastapi import HTTPException

    with patch("services.gateway_service.main.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.request.side_effect = httpx.ConnectError("boom")
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        with pytest.raises(HTTPException) as exc_info:
            await gateway_main.invoke("approval-agent", "escalations", _request(method="GET", body=b""))

    assert exc_info.value.status_code == 502
