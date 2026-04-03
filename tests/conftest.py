import json
from collections.abc import AsyncIterator, Awaitable, Callable

from jnav.store import IndexedEntry

SAMPLE_LINES = [
    json.dumps({"level": "INFO", "message": "hello"}),
    json.dumps({"level": "ERROR", "message": "boom"}),
    json.dumps({"level": "DEBUG", "message": "trace", "nested": '{"a": 1}'}),
]


async def fake_line_reader(lines: list[str]) -> AsyncIterator[str]:
    """Simulate a reader that yields lines then stops."""
    for line in lines:
        yield line


def make_collector() -> tuple[
    list[list[IndexedEntry]], Callable[[list[IndexedEntry]], Awaitable[None]]
]:
    items: list[list[IndexedEntry]] = []

    async def collect(item: list[IndexedEntry]) -> None:
        items.append(item)

    return items, collect


def make_signal_collector() -> tuple[list[None], Callable[[None], Awaitable[None]]]:
    items: list[None] = []

    async def collect(item: None) -> None:
        items.append(item)

    return items, collect
