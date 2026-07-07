import asyncio

import pytest

from services.gateway_service.bulkhead import Bulkhead

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_try_enter_succeeds_under_limit():
    bulkhead = Bulkhead(max_concurrent=2)
    assert await bulkhead.try_enter() is True
    assert await bulkhead.try_enter() is True
    assert bulkhead.in_use == 2


@pytest.mark.asyncio
async def test_try_enter_fails_when_full():
    bulkhead = Bulkhead(max_concurrent=1)
    assert await bulkhead.try_enter() is True
    assert await bulkhead.try_enter() is False
    assert bulkhead.in_use == 1


@pytest.mark.asyncio
async def test_exit_frees_a_slot():
    bulkhead = Bulkhead(max_concurrent=1)
    await bulkhead.try_enter()
    await bulkhead.exit()
    assert bulkhead.in_use == 0
    assert await bulkhead.try_enter() is True


@pytest.mark.asyncio
async def test_exit_never_goes_negative():
    bulkhead = Bulkhead(max_concurrent=1)
    await bulkhead.exit()
    await bulkhead.exit()
    assert bulkhead.in_use == 0


@pytest.mark.asyncio
async def test_concurrent_try_enter_never_exceeds_limit():
    """Fires many concurrent try_enter() calls and confirms the bulkhead's internal lock
    prevents more than max_concurrent from ever succeeding at once — the actual race condition
    a bulkhead exists to prevent."""
    bulkhead = Bulkhead(max_concurrent=3)
    results = await asyncio.gather(*[bulkhead.try_enter() for _ in range(20)])
    assert sum(1 for r in results if r) == 3
    assert bulkhead.in_use == 3
