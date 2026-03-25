import asyncio
import hashlib
import sys
from asyncio import Queue
from collections.abc import AsyncIterator
from pathlib import Path

import click

from .app import JnavApp
from .logging import init_logging
from .parsing import ParsedEntry
from .pipeline import stream_to_queue
from .reading import read_file, read_pipe, setup_stdin_pipe

_STATE_DIR = Path.home() / ".local" / "share" / "jnav"


def _state_file_for(file_path: str) -> Path:
    key = hashlib.sha256(str(Path(file_path).resolve()).encode()).hexdigest()[:16]
    return _STATE_DIR / f"{key}.json"


def _get_input_iterator(file: str | None) -> AsyncIterator[str] | None:
    if file:
        return read_file(file)
    elif not sys.stdin.isatty():
        pipe = setup_stdin_pipe()
        return read_pipe(pipe)

    return None


async def _run(file: str | None, initial_filter: str) -> None:
    lines = _get_input_iterator(file)

    if lines is None:
        click.echo("Usage: jnav [FILE] or pipe JSONL via stdin", err=True)
        raise SystemExit(1)

    entry_queue: Queue[ParsedEntry] = Queue(maxsize=1000)
    stream_task = asyncio.create_task(stream_to_queue(lines, entry_queue))

    state_file = _state_file_for(file) if file else None
    app = JnavApp(
        entry_queue=entry_queue,
        initial_filter=initial_filter,
        state_file=state_file,
    )
    app.title = "jnav"
    await app.run_async()
    stream_task.cancel()


@click.command()
@click.argument("file", required=False, type=click.Path(exists=True))
@click.option(
    "-f", "--filter", "initial_filter", default="", help="Initial jq filter expression"
)
def main(file: str | None, initial_filter: str) -> None:
    """Interactive JSON log viewer with jq filtering."""
    init_logging()
    asyncio.run(_run(file, initial_filter))


if __name__ == "__main__":
    main()
