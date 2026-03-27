import asyncio
import hashlib
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import aioreactive as rx
import click

from jnav.field_manager import FieldManager
from jnav.filter_provider import FilterProvider
from jnav.log_model import LogModel
from jnav.search_engine import SearchEngine
from jnav.store import Store

from .app import JnavApp
from .buffer import buffer_time_or_count
from .logging import init_logging
from .parsing import parse_line, preprocess_entry
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


async def _run(file: str | None) -> None:
    lines = _get_input_iterator(file)

    if lines is None:
        click.echo("Usage: jnav [FILE] or pipe JSONL via stdin", err=True)
        raise SystemExit(1)

    filter_provider = FilterProvider()
    fields = FieldManager()
    store = Store()
    model = LogModel(
        store=store,
        filter_provider=filter_provider,
    )

    search = SearchEngine(model)

    await model.start()
    await search.start()

    entry_stream = rx.from_async_iterable(
        buffer_time_or_count(
            rx.pipe(
                rx.from_async_iterable(lines),
                rx.map(lambda line: parse_line(line)),
                rx.filter(lambda result: result.is_ok()),
                rx.map(lambda entry: preprocess_entry(entry.ok)),
            ),
            max_count=100,
            timeout=0.1,
        )
    )

    await entry_stream.subscribe_async(store.append_entries)

    state_file = _state_file_for(file) if file else None
    app = JnavApp(
        model=model,
        filter_provider=filter_provider,
        fields=fields,
        search=search,
        state_file=state_file,
    )
    app.title = "jnav"
    await app.run_async()


@click.command()
@click.argument("file", required=False, type=click.Path(exists=True))
def main(file: str | None) -> None:
    """Interactive JSON log viewer with jq filtering."""
    init_logging()
    asyncio.run(_run(file))


if __name__ == "__main__":
    main()
