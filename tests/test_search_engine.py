from typing import Any

import pytest
import pytest_asyncio

from jnav.filter_provider import FilterProvider
from jnav.log_model import LogModel
from jnav.search_engine import SearchEngine, entry_matches_search
from jnav.store import Store

from .conftest import make_entry, make_signal_collector

type Env = tuple[Store, LogModel, SearchEngine]


def _entry(level: str, message: str = "") -> dict[str, Any]:
    return {"level": level, "message": message}


@pytest_asyncio.fixture
async def env() -> Env:
    fp = FilterProvider()
    store = Store()
    model = LogModel(store=store, filter_provider=fp)
    search = SearchEngine(model)
    await model.start()
    await search.start()
    return store, model, search


class TestEntryMatchesSearch:
    def test_matches_string_value(self) -> None:
        assert entry_matches_search({"msg": "hello world"}, "hello")

    def test_case_insensitive(self) -> None:
        assert entry_matches_search({"msg": "Hello World"}, "hello")

    def test_no_match(self) -> None:
        assert not entry_matches_search({"msg": "hello"}, "goodbye")

    def test_nested_dict(self) -> None:
        assert entry_matches_search({"a": {"b": "needle"}}, "needle")

    def test_nested_list(self) -> None:
        assert entry_matches_search({"items": ["foo", "bar"]}, "bar")

    def test_numeric_value(self) -> None:
        assert entry_matches_search({"code": 404}, "404")


class TestSearchEngineState:
    @pytest.mark.asyncio
    async def test_initial_state(self, env: Env) -> None:
        _, _, search = env
        assert search.term == ""
        assert search.matches == []
        assert not search.active

    @pytest.mark.asyncio
    async def test_set_term(self, env: Env) -> None:
        _, _, search = env
        await search.set_term("hello")
        assert search.term == "hello"
        assert search.active

    @pytest.mark.asyncio
    async def test_clear(self, env: Env) -> None:
        _, _, search = env
        await search.set_term("hello")
        await search.clear()
        assert search.term == ""
        assert search.matches == []
        assert not search.active

    @pytest.mark.asyncio
    async def test_set_term_emits_on_change(self, env: Env) -> None:
        _, _, search = env
        events, collect = make_signal_collector()
        await search.on_change.subscribe_async(collect)

        await search.set_term("test")

        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_clear_emits_on_change(self, env: Env) -> None:
        _, _, search = env
        await search.set_term("test")

        events, collect = make_signal_collector()
        await search.on_change.subscribe_async(collect)
        await search.clear()

        assert len(events) == 1


class TestSearchEngineMatches:
    @pytest.mark.asyncio
    async def test_matches_are_store_indices(self, env: Env) -> None:
        """Matches contain store indices, not list positions."""
        store, _, search = env
        await store.append_entries(
            [
                make_entry(_entry("INFO", "hello")),
                make_entry(_entry("ERROR", "world")),
                make_entry(_entry("INFO", "hello again")),
            ]
        )

        await search.set_term("hello")

        assert search.matches == [0, 2]

    @pytest.mark.asyncio
    async def test_no_matches(self, env: Env) -> None:
        store, _, search = env
        await store.append_entries([make_entry(_entry("INFO", "hello"))])

        await search.set_term("goodbye")

        assert search.matches == []

    @pytest.mark.asyncio
    async def test_matches_cleared_on_clear(self, env: Env) -> None:
        store, _, search = env
        await store.append_entries([make_entry(_entry("INFO", "hello"))])
        await search.set_term("hello")
        assert search.matches == [0]

        await search.clear()

        assert search.matches == []

    @pytest.mark.asyncio
    async def test_matches_recomputed_on_rebuild(self, env: Env) -> None:
        store, model, search = env
        await store.append_entries(
            [
                make_entry(_entry("INFO", "hello")),
                make_entry(_entry("ERROR", "world")),
            ]
        )
        await search.set_term("hello")
        assert search.matches == [0]

        await model.on_rebuild.asend(None)

        assert search.matches == [0]

    @pytest.mark.asyncio
    async def test_matches_extended_on_append(self, env: Env) -> None:
        store, _, search = env
        await store.append_entries([make_entry(_entry("INFO", "hello"))])
        await search.set_term("hello")
        assert search.matches == [0]

        await store.append_entries(
            [
                make_entry(_entry("ERROR", "world")),
                make_entry(_entry("INFO", "hello again")),
            ]
        )

        # Store indices: 0=hello, 1=world, 2=hello again
        assert search.matches == [0, 2]

    @pytest.mark.asyncio
    async def test_append_no_new_matches(self, env: Env) -> None:
        store, _, search = env
        await store.append_entries([make_entry(_entry("INFO", "hello"))])
        await search.set_term("hello")

        events, collect = make_signal_collector()
        await search.on_change.subscribe_async(collect)

        await store.append_entries([make_entry(_entry("ERROR", "world"))])

        assert search.matches == [0]
        assert len(events) == 0

    @pytest.mark.asyncio
    async def test_no_matches_when_no_term(self, env: Env) -> None:
        store, _, search = env
        await store.append_entries([make_entry(_entry("INFO", "hello"))])

        assert search.matches == []

    @pytest.mark.asyncio
    async def test_set_empty_term_clears_matches(self, env: Env) -> None:
        store, _, search = env
        await store.append_entries([make_entry(_entry("INFO", "hello"))])
        await search.set_term("hello")
        assert search.matches == [0]

        await search.set_term("")

        assert search.matches == []

    @pytest.mark.asyncio
    async def test_rebuild_with_no_term_is_noop(self, env: Env) -> None:
        store, model, search = env
        await store.append_entries([make_entry(_entry("INFO", "hello"))])

        events, collect = make_signal_collector()
        await search.on_change.subscribe_async(collect)

        await model.on_rebuild.asend(None)

        assert search.matches == []
        assert len(events) == 0

    @pytest.mark.asyncio
    async def test_append_with_no_term_is_noop(self, env: Env) -> None:
        store, _, search = env

        events, collect = make_signal_collector()
        await search.on_change.subscribe_async(collect)

        await store.append_entries([make_entry(_entry("INFO", "hello"))])

        assert search.matches == []
        assert len(events) == 0

    @pytest.mark.asyncio
    async def test_matches_include_filtered_out_entries(self, env: Env) -> None:
        """Matches are store indices, independent of visible_indices."""
        store, model, search = env
        del model  # unused
        await store.append_entries(
            [
                make_entry(_entry("INFO", "hello")),
                make_entry(_entry("ERROR", "hello")),
            ]
        )
        # Even if entry 0 is filtered out, search still finds it
        await search.set_term("hello")

        assert search.matches == [0, 1]
