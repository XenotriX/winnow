import asyncio
from collections.abc import AsyncIterable

from aioreactive import AsyncObservable, to_async_iterable


async def buffer_time_or_count[T](
    source: AsyncObservable[T],
    max_count: int = 500,
    timeout: float = 0.1,
) -> AsyncIterable[list[T]]:
    batch: list[T] = []
    iterator = aiter(to_async_iterable(source))
    next_task: asyncio.Task[T] | None = None
    try:
        while True:
            # Create a new task if we don't already have one pending
            if next_task is None:
                next_task = asyncio.ensure_future(anext(iterator))

            # Wait for either the next item or the timeout
            done, _ = await asyncio.wait({next_task}, timeout=timeout)

            # If the next item is ready, add it to the batch
            if next_task in done:
                # If the iterator is exhausted, yield any remaining batch and exit
                try:
                    entry = next_task.result()
                except StopAsyncIteration:
                    if batch:
                        yield batch
                    return

                # Append the item to the batch and reset the next task
                next_task = None
                batch.append(entry)

                # Yield the batch if we've reached the max count
                if len(batch) >= max_count:
                    yield batch
                    batch = []
            # If the timeout expired, yield the current batch if it's not empty
            elif batch:
                yield batch
                batch = []
    finally:
        if next_task is not None and not next_task.done():
            next_task.cancel()
