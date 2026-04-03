from collections.abc import AsyncIterator

import aioreactive as rx
import pytest


class TestBufferTimeOrCount:
    @pytest.mark.asyncio
    async def test_buffer_by_count(self) -> None:
        """When items exceed max_count, a batch is yielded."""
        from jnav.buffer import buffer_time_or_count

        items = list(range(10))

        async def source() -> AsyncIterator[int]:
            for i in items:
                yield i

        observable = rx.from_async_iterable(source())
        batches: list[list[int]] = []
        async for batch in buffer_time_or_count(observable, max_count=3, timeout=10.0):
            batches.append(batch)

        all_items = [item for batch in batches for item in batch]
        assert all_items == items
        assert any(len(b) == 3 for b in batches)

    @pytest.mark.asyncio
    async def test_buffer_flushes_remainder(self) -> None:
        """Leftover items are yielded when the source completes."""
        from jnav.buffer import buffer_time_or_count

        async def source() -> AsyncIterator[int]:
            yield 1
            yield 2

        observable = rx.from_async_iterable(source())
        batches: list[list[int]] = []
        async for batch in buffer_time_or_count(
            observable, max_count=100, timeout=10.0
        ):
            batches.append(batch)

        all_items = [item for batch in batches for item in batch]
        assert all_items == [1, 2]
