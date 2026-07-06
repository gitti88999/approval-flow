import asyncio


class Bulkhead:
    """Caps concurrent usage of one resource (e.g. calls to a specific downstream service) so a
    slow or failing dependency can't exhaust capacity that other dependencies also need — the
    classic bulkhead pattern (N3). Rejects immediately when full instead of queueing."""

    def __init__(self, max_concurrent: int):
        self._max = max_concurrent
        self._current = 0
        self._lock = asyncio.Lock()

    async def try_enter(self) -> bool:
        async with self._lock:
            if self._current >= self._max:
                return False
            self._current += 1
            return True

    async def exit(self) -> None:
        async with self._lock:
            self._current = max(0, self._current - 1)

    @property
    def in_use(self) -> int:
        return self._current
