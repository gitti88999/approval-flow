import pytest
from unittest.mock import patch

from services.payment_service import main as payment_main
from services.payment_service import dapr_client

pytestmark = pytest.mark.integration


class DummyRequest:
    def __init__(self, payload):
        self._payload = payload

    async def json(self):
        return self._payload


def _event(tracking_id="TRK-1", total=100.0, notes=None):
    return {"data": {"tracking_id": tracking_id, "invoice": {"total": total, "notes": notes}}}


@pytest.mark.asyncio
async def test_successful_payment_commits_and_publishes():
    with patch.object(dapr_client, "get_payment_state", return_value=None), \
         patch.object(dapr_client, "save_payment_state") as mock_save, \
         patch.object(dapr_client, "publish_outcome") as mock_publish:
        result = await payment_main.handle_payment(DummyRequest(_event()))

    assert result["outcome"] == "paid"
    statuses = [call.args[1]["status"] for call in mock_save.call_args_list]
    assert statuses == ["reserved", "paid"]
    mock_publish.assert_called_once_with("TRK-1", "paid", "Payment completed successfully")


@pytest.mark.asyncio
async def test_failed_charge_compensates_reservation():
    with patch.object(dapr_client, "get_payment_state", return_value=None), \
         patch.object(dapr_client, "save_payment_state") as mock_save, \
         patch.object(dapr_client, "publish_outcome") as mock_publish:
        result = await payment_main.handle_payment(
            DummyRequest(_event(notes="please SIMULATE_PAYMENT_FAILURE"))
        )

    assert result["outcome"] == "failed"
    statuses = [call.args[1]["status"] for call in mock_save.call_args_list]
    assert statuses == ["reserved", "compensated"]
    mock_publish.assert_called_once()
    assert mock_publish.call_args.args[1] == "failed"


@pytest.mark.asyncio
async def test_duplicate_event_is_a_noop():
    with patch.object(dapr_client, "get_payment_state", return_value={"status": "paid"}), \
         patch.object(dapr_client, "save_payment_state") as mock_save, \
         patch.object(dapr_client, "publish_outcome") as mock_publish:
        result = await payment_main.handle_payment(DummyRequest(_event()))

    assert "already processed" in result.get("note", "")
    mock_save.assert_not_called()
    mock_publish.assert_not_called()


@pytest.mark.asyncio
async def test_redelivery_while_reserved_is_a_noop():
    """A redelivered payment-required event arriving after the first delivery reached
    'reserved' but before it reached a terminal state must not trigger a second charge —
    the gap this closes: checking only for terminal states would have let this through."""
    with patch.object(dapr_client, "get_payment_state", return_value={"status": "reserved"}), \
         patch.object(dapr_client, "save_payment_state") as mock_save, \
         patch.object(dapr_client, "publish_outcome") as mock_publish:
        result = await payment_main.handle_payment(DummyRequest(_event()))

    assert "already processed" in result.get("note", "")
    mock_save.assert_not_called()
    mock_publish.assert_not_called()
