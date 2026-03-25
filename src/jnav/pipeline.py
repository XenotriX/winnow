import logging
from asyncio import Queue
from collections.abc import AsyncIterator

from .parsing import ParsedEntry, parse_line, preprocess_entry

logger = logging.getLogger(__name__)


async def stream_to_queue(
    lines: AsyncIterator[str],
    queue: Queue[ParsedEntry],
) -> None:
    """Read lines from an async iterator, parse them, and push ParsedEntries to the queue."""
    count = 0
    async for line in lines:
        try:
            entry = parse_line(line)
        except ValueError as e:
            logger.warning("parse_error", exc_info=e, extra={"line": line.strip()})
            continue
        parsed = preprocess_entry(entry)
        await queue.put(parsed)
        count += 1
