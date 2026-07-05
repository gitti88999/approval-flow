from unittest.mock import AsyncMock, patch

import pytest

from services.approval_agent import main as agent_main


@pytest.mark.asyncio
async def test_status_processing_when_nothing_recorded_yet():
    with patch.object(agent_main, "get_evaluation", new=AsyncMock(return_value=None)), \
         patch("services.approval_agent.main.escalation.get_escalation", return_value=None):
        result = await agent_main.get_status("T-UNKNOWN")

    assert result["stage"] == "processing"


@pytest.mark.asyncio
async def test_status_auto_approved_and_paid():
    evaluation = {"recommendation": "approve", "reason": "MEAL-01", "confidence": 0.9, "payment_status": "paid"}
    with patch.object(agent_main, "get_evaluation", new=AsyncMock(return_value=evaluation)), \
         patch("services.approval_agent.main.escalation.get_escalation", return_value=None):
        result = await agent_main.get_status("T1")

    assert result["stage"] == "paid"
    assert result["recommendation"] == "approve"


@pytest.mark.asyncio
async def test_status_auto_approved_payment_failed():
    evaluation = {
        "recommendation": "approve",
        "reason": "MEAL-01",
        "confidence": 0.9,
        "payment_status": "failed",
        "payment_reason": "Payment gateway declined the charge",
    }
    with patch.object(agent_main, "get_evaluation", new=AsyncMock(return_value=evaluation)), \
         patch("services.approval_agent.main.escalation.get_escalation", return_value=None):
        result = await agent_main.get_status("T2")

    assert result["stage"] == "payment_failed"
    assert "declined" in result["message"]


@pytest.mark.asyncio
async def test_status_escalated_pending():
    esc = {"recommendation": "human_review", "reason": "Amount exceeds ceiling", "confidence": 1.0, "status": "pending"}
    with patch.object(agent_main, "get_evaluation", new=AsyncMock(return_value=None)), \
         patch("services.approval_agent.main.escalation.get_escalation", return_value=esc):
        result = await agent_main.get_status("T3")

    assert result["stage"] == "escalated"


@pytest.mark.asyncio
async def test_status_awaiting_info():
    esc = {
        "recommendation": "human_review",
        "reason": "over $500",
        "confidence": 1.0,
        "status": "info_requested",
        "approver_notes": "need business justification",
    }
    with patch.object(agent_main, "get_evaluation", new=AsyncMock(return_value=None)), \
         patch("services.approval_agent.main.escalation.get_escalation", return_value=esc):
        result = await agent_main.get_status("T4")

    assert result["stage"] == "awaiting_info"
    assert "business justification" in result["message"]


@pytest.mark.asyncio
async def test_status_rejected():
    esc = {
        "recommendation": "human_review",
        "reason": "hard stop",
        "confidence": 1.0,
        "status": "rejected",
        "approver": "mgr@example.com",
        "approver_notes": "not eligible",
    }
    with patch.object(agent_main, "get_evaluation", new=AsyncMock(return_value=None)), \
         patch("services.approval_agent.main.escalation.get_escalation", return_value=esc):
        result = await agent_main.get_status("T5")

    assert result["stage"] == "rejected"
    assert "mgr@example.com" in result["message"]
