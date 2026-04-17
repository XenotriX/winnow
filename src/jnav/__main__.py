import asyncio
import hashlib
import logging
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import cast

import aioreactive as rx
import click
from platformdirs import user_data_dir

from jnav.filter_provider import FilterProvider
from jnav.log_model import LogModel
from jnav.role_mapper import RoleMapper
from jnav.search_engine import SearchEngine
from jnav.selector_provider import SelectorProvider
from jnav.store import Store

from .app import JnavApp
from .buffer import buffer_time_or_count
from .logging import init_logging
from .parsing import ParsedEntry, parse_entry
from .reading import read_file, read_pipe, setup_stdin_pipe

logging.getLogger("aioreactive").setLevel(logging.WARNING)

_STATE_DIR = Path(user_data_dir("jnav"))


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


async def _run(file: str | None, follow: bool) -> None:
    lines = _get_input_iterator(file)

    if lines is None:
        click.echo("Usage: jnav [FILE] or pipe JSONL via stdin", err=True)
        raise SystemExit(1)

    filter_provider = FilterProvider()
    role_mapper = RoleMapper()
    selectors = SelectorProvider()
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
                rx.map(lambda line: parse_entry(line)),
                rx.filter(lambda result: result is not None),
                rx.map(lambda entry: cast(ParsedEntry, entry)),
            ),
            max_count=10000,
            timeout=0.1,
        )
    )

    await entry_stream.subscribe_async(store.append_entries)

    state_file = _state_file_for(file) if file else None
    app = JnavApp(
        model=model,
        filter_provider=filter_provider,
        role_mapper=role_mapper,
        selectors=selectors,
        search=search,
        state_file=state_file,
        follow=follow,
        file_name=file if file else "<stdin>",
    )
    app.title = "jnav"
    await app.run_async()


@click.command()
@click.argument("file", required=False, type=click.Path(exists=True))
@click.option("--follow", "-f", is_flag=True, help="Follow the file for new entries")
@click.version_option()
def main(file: str | None, follow: bool) -> None:
    """Interactive JSON log viewer with jq filtering."""
    init_logging()
    asyncio.run(_run(file, follow=follow))


if __name__ == "__main__":
    main()
