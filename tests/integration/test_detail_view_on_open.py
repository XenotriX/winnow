# pyright: reportPrivateUsage=false

import pytest

from jnav.app import JnavApp
from jnav.detail_tree import DetailTree
from jnav.filter_provider import FilterProvider
from jnav.log_list_view import LogListView
from jnav.log_model import LogModel
from jnav.role_mapper import RoleMapper
from jnav.search_engine import SearchEngine
from jnav.selector_provider import SelectorProvider
from jnav.store import Store
from tests.conftest import make_entry


async def _make_app(*, detail_visible: bool) -> tuple[JnavApp, Store]:
    store = Store()
    filter_provider = FilterProvider()
    model = LogModel(store=store, filter_provider=filter_provider)
    role_mapper = RoleMapper()
    selectors = SelectorProvider()
    search = SearchEngine(model)
    await model.start()
    await search.start()
    app = JnavApp(
        model=model,
        filter_provider=filter_provider,
        role_mapper=role_mapper,
        selectors=selectors,
        search=search,
        file_name="test.log",
        detail_visible=detail_visible,
    )
    return app, store


class TestDetailViewOnOpen:
    @pytest.mark.asyncio
    async def test_shows_first_entry_when_detail_visible_and_entries_arrive_after_mount(
        self,
    ) -> None:
        """Opening a file with detail view already visible must populate the detail
        view with the first entry once entries arrive.

        Regression: if the store is empty at app-mount time (entries load
        asynchronously) and the detail panel is pre-visible, the detail tree
        must still show the first entry once data flows in.
        """
        app, store = await _make_app(detail_visible=True)

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()

            await store.append_entries([
                make_entry({"level": "INFO", "message": "first"}),
                make_entry({"level": "ERROR", "message": "second"}),
            ])
            await pilot.pause()

            tree = app.query_one("#detail-tree", DetailTree)
            assert tree.entry is not None, (
                "DetailTree has no entry after data arrived post-mount"
            )
            assert tree.entry.expanded["message"] == "first"

    @pytest.mark.asyncio
    async def test_shows_first_entry_when_detail_visible_and_entries_preloaded(
        self,
    ) -> None:
        """Baseline: when entries are already in the store at mount time, the
        detail view shows the first entry too."""
        app, store = await _make_app(detail_visible=True)
        await store.append_entries([
            make_entry({"level": "INFO", "message": "first"}),
        ])

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()

            tree = app.query_one("#detail-tree", DetailTree)
            assert tree.entry is not None
            assert tree.entry.expanded["message"] == "first"

    @pytest.mark.asyncio
    async def test_log_list_highlights_first_entry_when_entries_arrive_after_mount(
        self,
    ) -> None:
        """Sanity: once entries arrive post-mount the LogListView cursor lands
        on the first entry."""
        app, store = await _make_app(detail_visible=False)

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()

            await store.append_entries([
                make_entry({"level": "INFO", "message": "first"}),
            ])
            await pilot.pause()

            lv = app.query_one("#log-list", LogListView)
            assert lv.count() == 1
            assert lv.index == 0
