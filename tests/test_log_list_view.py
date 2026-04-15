# pyright: reportPrivateUsage=false

from typing import override
from unittest.mock import Mock

import pytest
from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widget import Widget

from jnav.filter_provider import FilterProvider
from jnav.log_list_view import LogListView
from jnav.log_model import LogModel
from jnav.parsing import ParsedEntry
from jnav.role_mapper import RoleMapper
from jnav.search_engine import SearchEngine
from jnav.selector_provider import SelectorProvider
from jnav.store import Store

from .conftest import make_entry


def _make_list_view(store_indices: list[int]) -> LogListView:
    lv = LogListView.__new__(LogListView)
    model = Mock()
    model.visible_indices = store_indices
    lv._log_model = model
    return lv


def test_exact_match():
    lv = _make_list_view([0, 2, 5, 8])
    assert lv._closest_list_index(5) == 2


def test_closest_rounds_down():
    lv = _make_list_view([0, 3, 7, 10])
    assert lv._closest_list_index(4) == 1


def test_closest_rounds_up():
    lv = _make_list_view([0, 3, 7, 10])
    assert lv._closest_list_index(6) == 2


def test_before_first():
    lv = _make_list_view([5, 10, 15])
    assert lv._closest_list_index(0) == 0


def test_after_last():
    lv = _make_list_view([5, 10, 15])
    assert lv._closest_list_index(100) == 2


def test_single_item():
    lv = _make_list_view([42])
    assert lv._closest_list_index(0) == 0
    assert lv._closest_list_index(42) == 0
    assert lv._closest_list_index(100) == 0


def test_equidistant_prefers_earlier():
    lv = _make_list_view([0, 4, 8])
    assert lv._closest_list_index(2) == 0


def test_closest_list_index_empty_returns_zero():
    lv = _make_list_view([])
    assert lv._closest_list_index(0) == 0
    assert lv._closest_list_index(999) == 0


def _info(message: str = "") -> ParsedEntry:
    return make_entry({"level": "INFO", "message": message})


def _error(message: str = "") -> ParsedEntry:
    return make_entry({"level": "ERROR", "message": message})


class _Harness(App[None]):
    def __init__(
        self,
        *,
        entries: list[ParsedEntry] | None = None,
        wrap_in_parent: bool = False,
    ) -> None:
        super().__init__()
        self._entries = entries or []
        self._wrap_in_parent = wrap_in_parent
        self.store = Store()
        self.filter_provider = FilterProvider()
        self.log_model = LogModel(self.store, self.filter_provider)
        self.role_mapper = RoleMapper()
        self.selectors = SelectorProvider()
        self.search = SearchEngine(self.log_model)

    @override
    def compose(self) -> ComposeResult:
        lv = LogListView(
            model=self.log_model,
            role_mapper=self.role_mapper,
            selectors=self.selectors,
            search=self.search,
            filter_provider=self.filter_provider,
            follow=False,
        )
        if self._wrap_in_parent:
            yield Vertical(lv, id="parent")
        else:
            yield lv

    async def on_mount(self) -> None:
        await self.log_model.start()
        await self.search.start()
        await self.store.append_entries(self._entries)


def _query_lv(app: _Harness) -> LogListView:
    return app.query_one(LogListView)


class TestCheckAction:
    @pytest.mark.asyncio
    async def test_toggle_expanded_enabled_only_with_active_selectors(self):
        app = _Harness(entries=[_info("hi")])
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            lv = _query_lv(app)
            assert lv.check_action("toggle_expanded", ()) is False

            await app.selectors.add_selector(".message")
            await pilot.pause()

            assert lv.check_action("toggle_expanded", ()) is True

    @pytest.mark.asyncio
    async def test_other_actions_always_enabled(self):
        app = _Harness(entries=[_info("hi")])
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            lv = _query_lv(app)
            assert lv.check_action("text_filter", ()) is True
            assert lv.check_action("jump_top", ()) is True


class TestMountAndRender:
    @pytest.mark.asyncio
    async def test_mounts_with_empty_model(self):
        app = _Harness()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            lv = _query_lv(app)
            assert lv.count() == 0

    @pytest.mark.asyncio
    async def test_render_produces_output_with_entries(self):
        app = _Harness(entries=[_info("hello")])
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            lv = _query_lv(app)
            assert lv.count() == 1
            assert lv.render() != ""


class TestInitialBuild:
    @pytest.mark.asyncio
    async def test_discovers_fields_from_existing_entries(self):
        app = _Harness(entries=[_info("hi"), _error("boom")])
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            lv = _query_lv(app)
            await lv.initial_build()
            assert "level" in app.role_mapper.all_fields
            assert "message" in app.role_mapper.all_fields
            assert lv.index == 0

    @pytest.mark.asyncio
    async def test_empty_model_does_not_set_index(self):
        app = _Harness()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            lv = _query_lv(app)
            await lv.initial_build()
            assert lv.count() == 0


class TestFocusBlur:
    @pytest.mark.asyncio
    async def test_focus_adds_focused_class_to_parent(self):
        app = _Harness(entries=[_info("hi")], wrap_in_parent=True)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            lv = _query_lv(app)
            parent = lv.parent
            assert isinstance(parent, Widget)
            lv.on_focus()
            assert parent.has_class("focused")

    @pytest.mark.asyncio
    async def test_blur_removes_focused_class_from_parent(self):
        app = _Harness(entries=[_info("hi")], wrap_in_parent=True)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            lv = _query_lv(app)
            parent = lv.parent
            assert isinstance(parent, Widget)
            parent.add_class("focused")
            lv.on_blur()
            assert not parent.has_class("focused")


class TestSetExpandedMode:
    @pytest.mark.asyncio
    async def test_toggles_flag(self):
        app = _Harness(entries=[_info("hi")])
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            lv = _query_lv(app)
            assert lv.expanded_mode is True

            lv.set_expanded_mode(False)
            assert lv.expanded_mode is False

            lv.set_expanded_mode(True)
            assert lv.expanded_mode is True

    @pytest.mark.asyncio
    async def test_action_toggle_expanded_flips_mode(self):
        app = _Harness(entries=[_info("hi")])
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            lv = _query_lv(app)
            assert lv.expanded_mode is True

            lv.action_toggle_expanded()
            assert lv.expanded_mode is False


class TestFilterPauseAction:
    @pytest.mark.asyncio
    async def test_noop_when_no_filters_defined(self):
        app = _Harness(entries=[_info("hi")])
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            lv = _query_lv(app)
            assert app.log_model.filtering_enabled is True

            await lv.action_toggle_filters_pause()

            assert app.log_model.filtering_enabled is True

    @pytest.mark.asyncio
    async def test_toggles_when_filter_exists(self):
        app = _Harness(entries=[_info("hi"), _error("boom")])
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            lv = _query_lv(app)
            await app.filter_provider.add_filter('.level == "ERROR"')
            await pilot.pause()
            assert app.log_model.filtering_enabled is True

            await lv.action_toggle_filters_pause()
            assert app.log_model.filtering_enabled is False

            await lv.action_toggle_filters_pause()
            assert app.log_model.filtering_enabled is True


class TestRebuildFlow:
    @pytest.mark.asyncio
    async def test_rebuild_on_filter_change_moves_cursor_to_closest_entry(self):
        app = _Harness(entries=[_info("a"), _info("b"), _error("c"), _info("d")])
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            lv = _query_lv(app)
            await lv.initial_build()
            lv.index = 2
            await pilot.pause()

            await app.filter_provider.add_filter('.level == "ERROR"')
            await pilot.pause()

            # Store idx 2 was the ERROR entry; after filtering it's the only one visible.
            assert lv.count() == 1
            assert lv.index == 0

    @pytest.mark.asyncio
    async def test_will_rebuild_on_empty_model_saves_zero_idx(self):
        app = _Harness()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            lv = _query_lv(app)

            # Adding a filter on an empty model still fires on_will_rebuild;
            # with no current entry, the saved store idx must default to 0.
            await app.filter_provider.add_filter('.level == "ERROR"')
            await pilot.pause()

            assert lv._saved_store_idx == 0


class TestCurrentIndex:
    @pytest.mark.asyncio
    async def test_returns_store_idx_at_cursor(self):
        app = _Harness(entries=[_info(f"m{i}") for i in range(3)])
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            lv = _query_lv(app)
            lv.index = 2
            await pilot.pause()
            assert lv.current_index() == 2

    @pytest.mark.asyncio
    async def test_returns_store_idx_with_filter_active(self):
        app = _Harness(
            entries=[_info("a"), _error("b"), _info("c"), _error("d")],
        )
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            lv = _query_lv(app)
            await app.filter_provider.add_filter('.level == "ERROR"')
            await pilot.pause()
            lv.index = 1
            await pilot.pause()
            assert lv.current_index() == 3

    @pytest.mark.asyncio
    async def test_returns_zero_when_all_entries_filtered_out(self):
        app = _Harness(entries=[_info("a"), _info("b")])
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            lv = _query_lv(app)
            await app.filter_provider.add_filter('.level == "ERROR"')
            await pilot.pause()
            assert lv.count() == 0
            assert lv.current_index() == 0


class TestJumpToIndex:
    @pytest.mark.asyncio
    async def test_moves_cursor_to_matching_store_idx(self):
        app = _Harness(
            entries=[_info("a"), _error("b"), _info("c"), _error("d")],
        )
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            lv = _query_lv(app)
            await app.filter_provider.add_filter('.level == "ERROR"')
            await pilot.pause()
            lv.jump_to_index(3)
            assert lv.index == 1

    @pytest.mark.asyncio
    async def test_missing_store_idx_leaves_cursor_unchanged(self):
        app = _Harness(
            entries=[_info("a"), _info("b"), _info("c"), _info("d")],
        )
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            lv = _query_lv(app)
            lv.index = 2
            await pilot.pause()

            lv.jump_to_index(99)

            assert lv.index == 2


class TestTextFilterAction:
    @pytest.mark.asyncio
    async def test_submitted_term_adds_filter(self):
        app = _Harness(entries=[_info("hi")])
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            lv = _query_lv(app)
            lv.action_text_filter()
            await pilot.pause()

            await pilot.press(*list("boom"))
            await pilot.press("enter")
            await pilot.pause()

            assert len(app.filter_provider.root.children) == 1

    @pytest.mark.asyncio
    async def test_cancelled_dialog_adds_no_filter(self):
        app = _Harness(entries=[_info("hi")])
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            lv = _query_lv(app)
            lv.action_text_filter()
            await pilot.pause()

            await pilot.press("escape")
            await pilot.pause()

            assert len(app.filter_provider.root.children) == 0


class TestKeyDispatch:
    @pytest.mark.asyncio
    async def test_gg_jumps_to_top(self):
        app = _Harness(entries=[_info(f"m{i}") for i in range(10)])
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            lv = _query_lv(app)
            lv.focus()
            lv.index = 5
            await pilot.pause()

            await pilot.press("g", "g")
            await pilot.pause()

            assert lv.index == 0
