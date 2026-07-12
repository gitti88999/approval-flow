from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Request

from services.gateway_service import main as gateway_main

pytestmark = pytest.mark.integration


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


@pytest.mark.asyncio
async def test_invoke_releases_bulkhead_slot_after_failure():
    """A failed call must still free its bulkhead slot (via the try/finally), or repeated
    upstream failures would eventually wedge the gateway shut for that service."""
    import httpx
    from fastapi import HTTPException

    bulkhead = gateway_main._bulkheads["approval-agent"]
    assert bulkhead.in_use == 0

    with patch("services.gateway_service.main.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.request.side_effect = httpx.ConnectError("boom")
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        with pytest.raises(HTTPException):
            await gateway_main.invoke("approval-agent", "escalations", _request(method="GET", body=b""))

    assert bulkhead.in_use == 0


@pytest.mark.asyncio
async def test_invoke_returns_503_when_bulkhead_is_full():
    from fastapi import HTTPException

    bulkhead = gateway_main._bulkheads["ingestion_service"]
    original_max = bulkhead._max
    bulkhead._max = 1
    assert await bulkhead.try_enter()  # fill the (now single) slot
    try:
        with pytest.raises(HTTPException) as exc_info:
            await gateway_main.invoke("ingestion_service", "submit", _request())
        assert exc_info.value.status_code == 503
    finally:
        await bulkhead.exit()
        bulkhead._max = original_max
