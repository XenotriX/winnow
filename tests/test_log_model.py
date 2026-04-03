from typing import Any

import pytest
import pytest_asyncio

from jnav.filter_provider import FilterProvider
from jnav.log_model import LogModel
from jnav.parsing import ParsedEntry, preprocess_entry
from jnav.store import IndexedEntry, Store

from .conftest import make_collector, make_signal_collector

type Env = tuple[Store, LogModel, FilterProvider]


def _entry(level: str, message: str = "") -> dict[str, Any]:
    return {"level": level, "message": message}


INFO: ParsedEntry = preprocess_entry(_entry("INFO"))
ERROR: ParsedEntry = preprocess_entry(_entry("ERROR"))
DEBUG: ParsedEntry = preprocess_entry(_entry("DEBUG"))

ERROR_FILTER: str = '.level == "ERROR"'


def _get_indices(batches: list[list[IndexedEntry]]) -> list[list[int]]:
    return [[i.index for i in batch] for batch in batches]


@pytest_asyncio.fixture
async def env() -> Env:
    fp = FilterProvider()
    store = Store()
    m = LogModel(store=store, filter_provider=fp)
    await m.start()
    return store, m, fp


class TestAccessors:
    @pytest.mark.asyncio
    async def test_model_accessors(self, env: Env) -> None:
        store, model, _ = env
        assert model.is_empty()
        assert model.count() == 0

        entry = preprocess_entry({"a": 1})
        await store.append_entries([entry])

        assert not model.is_empty()
        assert model.count() == 1
        assert model.get(0).entry is entry
        assert [ie.entry for ie in model.all()] == [entry]

    @pytest.mark.asyncio
    async def test_start_relays_store_events(self, env: Env) -> None:
        store, model, _ = env
        received, collect = make_collector()
        await model.on_append.subscribe_async(collect)

        entry = preprocess_entry({"level": "INFO"})
        await store.append_entries([entry])

        assert len(received) == 1
        assert received[0] == [IndexedEntry(0, entry)]


class TestNoFilters:
    @pytest.mark.asyncio
    async def test_all_entries_visible(self, env: Env) -> None:
        store, model, _ = env

        await store.append_entries([INFO, ERROR])

        assert model.visible_indices == [0, 1]

    @pytest.mark.asyncio
    async def test_incremental_append_extends_visible(self, env: Env) -> None:
        store, model, _ = env

        await store.append_entries([INFO])
        assert model.visible_indices == [0]

        await store.append_entries([ERROR])
        assert model.visible_indices == [0, 1]

    @pytest.mark.asyncio
    async def test_on_append_emits_new_visible_indices(self, env: Env) -> None:
        store, model, _ = env
        appended, collect = make_collector()
        await model.on_append.subscribe_async(collect)

        await store.append_entries([INFO])
        await store.append_entries([ERROR])

        assert _get_indices(appended) == [[0], [1]]


class TestWithFilters:
    @pytest.mark.asyncio
    async def test_new_entries_filtered_incrementally(self, env: Env) -> None:
        store, model, fp = env
        await fp.add_filter(ERROR_FILTER)

        await store.append_entries([INFO, ERROR, DEBUG])

        assert model.visible_indices == [1]

    @pytest.mark.asyncio
    async def test_on_append_emits_only_matched(self, env: Env) -> None:
        store, model, fp = env
        await fp.add_filter(ERROR_FILTER)

        appended, collect = make_collector()
        await model.on_append.subscribe_async(collect)

        await store.append_entries([INFO, ERROR])

        assert _get_indices(appended) == [[1]]

    @pytest.mark.asyncio
    async def test_on_append_not_emitted_when_nothing_matches(self, env: Env) -> None:
        store, model, fp = env
        await fp.add_filter('.level == "FATAL"')

        appended, collect = make_collector()
        await model.on_append.subscribe_async(collect)

        await store.append_entries([INFO])

        assert appended == []
        assert model.visible_indices == []


class TestRefilter:
    @pytest.mark.skip(reason="Error handling in apply_combined_filters needs rework")
    @pytest.mark.asyncio
    async def test_filter_error_keeps_all_visible(self, env: Env) -> None:
        """An invalid filter expression should not hide entries."""
        store, model, fp = env

        await store.append_entries([INFO])
        await fp.add_filter("not a valid jq expression !!!")

        assert model.visible_indices == [0]

    @pytest.mark.asyncio
    async def test_adding_filter_recomputes_visible(self, env: Env) -> None:
        store, model, fp = env

        await store.append_entries([INFO, ERROR, DEBUG])
        assert model.visible_indices == [0, 1, 2]

        await fp.add_filter(ERROR_FILTER)

        assert model.visible_indices == [1]

    @pytest.mark.asyncio
    async def test_on_rebuild_emitted_on_filter_change(self, env: Env) -> None:
        _, model, fp = env
        rebuilds, collect = make_signal_collector()
        await model.on_rebuild.subscribe_async(collect)

        await fp.add_filter(ERROR_FILTER)

        assert len(rebuilds) == 1


class TestFilterPause:
    @pytest.mark.asyncio
    async def test_pause_shows_all_entries(self, env: Env) -> None:
        store, model, fp = env

        await store.append_entries([INFO, ERROR])
        await fp.add_filter(ERROR_FILTER)
        assert model.visible_indices == [1]

        await model.pause_filtering()

        assert model.visible_indices == [0, 1]

    @pytest.mark.asyncio
    async def test_unpause_reapplies_filters(self, env: Env) -> None:
        store, model, fp = env

        await store.append_entries([INFO, ERROR])
        await fp.add_filter(ERROR_FILTER)
        await model.pause_filtering()
        assert model.visible_indices == [0, 1]

        await model.resume_filtering()

        assert model.visible_indices == [1]

    @pytest.mark.asyncio
    async def test_new_entries_unfiltered_when_paused(self, env: Env) -> None:
        store, model, fp = env
        await fp.add_filter(ERROR_FILTER)
        await model.pause_filtering()

        await store.append_entries([INFO, ERROR])

        assert model.visible_indices == [0, 1]
