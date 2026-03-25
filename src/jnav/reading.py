import asyncio
import logging
import os
import sys
from collections.abc import AsyncIterator
from io import BufferedReader

logger = logging.getLogger(__name__)


async def read_file(path: str) -> AsyncIterator[str]:
    """Yield lines from a file, tailing for new content at EOF."""
    with open(path, mode="r", errors="replace") as f:
        while True:
            line = f.readline()

            if not line:
                # EOF reached, wait for new lines
                await asyncio.sleep(0.1)
                continue

            logger.debug("line_read")
            yield line


async def read_pipe(pipe: BufferedReader) -> AsyncIterator[str]:
    """Yield lines from a pipe using asyncio stream reader."""
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, pipe)
    while not reader.at_eof():
        line_bytes = await reader.readline()
        if line_bytes:
            yield line_bytes.decode(errors="replace")


def setup_stdin_pipe() -> BufferedReader:
    """Duplicate stdin to a separate file descriptor.
    This is required for TUI input handling, while we read piped input.
    """
    pipe = os.fdopen(os.dup(sys.stdin.fileno()), "rb")
    sys.stdin.close()
    try:
        tty = open("/dev/tty")
    except OSError:
        pipe.close()
        raise
    sys.stdin = tty
    sys.__stdin__ = tty

    return pipe
