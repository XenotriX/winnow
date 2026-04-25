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

from jnav import state as app_state
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

logger = logging.getLogger(__name__)

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

    state_file = _state_file_for(file) if file else None
    if state_file:
        logger.info(
            "Loading state from file",
            extra={
                "log_file": file,
                "state_file": str(state_file),
            },
        )
        initial_state = app_state.load(state_file)
    else:
        logger.info(
            "No state file for input, starting with default state",
            extra={"log_file": file},
        )
        initial_state = app_state.AppState()

    filter_provider = FilterProvider()
    role_mapper = RoleMapper()
    selectors = SelectorProvider()
    store = Store()
    model = LogModel(
        store=store,
        filter_provider=filter_provider,
    )

    search = SearchEngine(model)

    await filter_provider.set_root(initial_state.filter_root)
    await selectors.set_selectors(initial_state.selectors)
    await role_mapper.set_mapping(initial_state.role_mapping)
    await model.set_filtering_enabled(initial_state.filtering_enabled)
    await search.set_term(initial_state.search_term)

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

    app = JnavApp(
        model=model,
        filter_provider=filter_provider,
        role_mapper=role_mapper,
        selectors=selectors,
        search=search,
        file_name=file if file else "<stdin>",
        expanded_mode=initial_state.expanded_mode,
        detail_visible=initial_state.detail_visible,
        show_selected_only=initial_state.show_selected_only,
        collapsed_paths=initial_state.collapsed_paths,
        follow=follow,
    )
    app.title = "jnav"
    final_state = await app.run_async()

    if state_file and final_state is not None:
        app_state.save(state_file, final_state)


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
