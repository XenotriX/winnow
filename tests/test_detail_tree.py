# pyright: reportPrivateUsage=false, reportAttributeAccessIssue=false, reportUninitializedInstanceVariable=false, reportUnknownMemberType=false, reportUnknownVariableType=false

import json
import os
from pathlib import Path
from typing import Any, cast, override
from unittest.mock import AsyncMock, Mock

import pytest
from textual.app import App, ComposeResult
from textual.binding import BindingsMap

from jnav.detail_tree import DetailTree, TreeNodeData
from jnav.field_mapping import FieldMapping, TimestampField
from jnav.filter_provider import FilterProvider
from jnav.log_model import LogModel
from jnav.role_mapper import RoleMapper
from jnav.search_engine import SearchEngine
from jnav.selector_provider import SelectorProvider
from jnav.store import Store

from .conftest import make_entry


def _make_detail_tree(
    *,
    cursor_data: TreeNodeData | None = None,
    has_selector: bool = False,
) -> DetailTree:
    dt = DetailTree.__new__(DetailTree)
    dt._bindings = BindingsMap([])
    dt._seq_buffer = ""
    dt._seq_pending = False
    dt._seq_saved_bindings = None
    dt._seq_saved_ancestor_bindings = []
    dt._seq_keymap = {}
    dt._seq_lookup = {}
    dt._seq_prefixes = {}
    dt._seq_base_bindings = None

    dt._entry = None
    dt._entry_index = 0
    dt.show_selected_only = False

    selectors = Mock(spec=SelectorProvider)
    selectors.has_selector = Mock(return_value=has_selector)
    selectors.add_selector = AsyncMock()
    selectors.remove_selector_by_path = AsyncMock()
    selectors.active_selectors = []
    dt._selectors = selectors

    filters = Mock(spec=FilterProvider)
    filters.add_filter = AsyncMock()
    dt._filters = filters

    search = Mock(spec=SearchEngine)
    search.term = ""
    dt._search = search

    role_mapper = Mock(spec=RoleMapper)
    role_mapper.mapping = FieldMapping()
    dt._role_mapper = role_mapper

    cursor_node = None
    if cursor_data is not None:
        cursor_node = Mock()
        cursor_node.data = cursor_data
    dt._cursor_node = cursor_node

    dt._rebuild_tree = Mock()  # type: ignore[method-assign]
    return dt


class TestShowEntry:
    def test_sets_entry_and_index(self) -> None:
        dt = _make_detail_tree()
        entry = make_entry({"level": "INFO"})
        dt.show_entry(entry, 7)
        assert dt._entry is entry
        assert dt._entry_index == 7

    def test_rebuilds_tree(self) -> None:
        dt = _make_detail_tree()
        entry = make_entry({"level": "INFO"})
        dt.show_entry(entry, 0)
        cast(Mock, dt._rebuild_tree).assert_called_once()

    def test_entry_property_returns_current_entry(self) -> None:
        dt = _make_detail_tree()
        entry = make_entry({"level": "INFO"})
        dt.show_entry(entry, 0)
        assert dt.entry is entry

    def test_entry_property_returns_none_by_default(self) -> None:
        dt = _make_detail_tree()
        assert dt.entry is None


class TestActionFilterValue:
    @pytest.mark.asyncio
    async def test_string_value_uses_quoted_literal(self) -> None:
        dt = _make_detail_tree(cursor_data={"path": "level", "value": "ERROR"})
        await dt.action_filter_value()
        cast(AsyncMock, dt._filters.add_filter).assert_awaited_once_with(
            '.level == "ERROR"'
        )

    @pytest.mark.asyncio
    async def test_integer_value_uses_bare_literal(self) -> None:
        dt = _make_detail_tree(cursor_data={"path": "count", "value": 42})
        await dt.action_filter_value()
        cast(AsyncMock, dt._filters.add_filter).assert_awaited_once_with(".count == 42")

    @pytest.mark.asyncio
    async def test_null_value_uses_null_literal(self) -> None:
        dt = _make_detail_tree(cursor_data={"path": "maybe", "value": None})
        await dt.action_filter_value()
        cast(AsyncMock, dt._filters.add_filter).assert_awaited_once_with(
            ".maybe == null"
        )

    @pytest.mark.asyncio
    async def test_bool_value_uses_bare_literal(self) -> None:
        dt = _make_detail_tree(cursor_data={"path": "flag", "value": True})
        await dt.action_filter_value()
        cast(AsyncMock, dt._filters.add_filter).assert_awaited_once_with(
            ".flag == true"
        )

    @pytest.mark.asyncio
    async def test_dict_value_is_noop(self) -> None:
        dt = _make_detail_tree(cursor_data={"path": "obj", "value": {"k": 1}})
        await dt.action_filter_value()
        cast(AsyncMock, dt._filters.add_filter).assert_not_awaited()

    @pytest.mark.asyncio
    async def test_list_value_is_noop(self) -> None:
        dt = _make_detail_tree(cursor_data={"path": "xs", "value": [1, 2]})
        await dt.action_filter_value()
        cast(AsyncMock, dt._filters.add_filter).assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_cursor_is_noop(self) -> None:
        dt = _make_detail_tree(cursor_data=None)
        await dt.action_filter_value()
        cast(AsyncMock, dt._filters.add_filter).assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cursor_without_data_is_noop(self) -> None:
        dt = _make_detail_tree()
        node = Mock()
        node.data = None
        dt._cursor_node = node
        await dt.action_filter_value()
        cast(AsyncMock, dt._filters.add_filter).assert_not_awaited()


class TestActionFilterHas:
    @pytest.mark.asyncio
    async def test_adds_not_null_filter(self) -> None:
        dt = _make_detail_tree(cursor_data={"path": "user.id", "value": "x"})
        await dt.action_filter_has()
        cast(AsyncMock, dt._filters.add_filter).assert_awaited_once_with(
            ".user.id != null"
        )

    @pytest.mark.asyncio
    async def test_uses_path_even_for_dict_value(self) -> None:
        dt = _make_detail_tree(cursor_data={"path": "obj", "value": {"k": 1}})
        await dt.action_filter_has()
        cast(AsyncMock, dt._filters.add_filter).assert_awaited_once_with(".obj != null")

    @pytest.mark.asyncio
    async def test_no_cursor_is_noop(self) -> None:
        dt = _make_detail_tree(cursor_data=None)
        await dt.action_filter_has()
        cast(AsyncMock, dt._filters.add_filter).assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cursor_without_data_is_noop(self) -> None:
        dt = _make_detail_tree()
        node = Mock()
        node.data = None
        dt._cursor_node = node
        await dt.action_filter_has()
        cast(AsyncMock, dt._filters.add_filter).assert_not_awaited()


class TestActionAddSelect:
    @pytest.mark.asyncio
    async def test_adds_prefixed_selector_when_absent(self) -> None:
        dt = _make_detail_tree(
            cursor_data={"path": "user.id", "value": 1},
            has_selector=False,
        )
        await dt.action_add_select()
        cast(Mock, dt._selectors.has_selector).assert_called_once_with(".user.id")
        cast(AsyncMock, dt._selectors.add_selector).assert_awaited_once_with(".user.id")
        cast(AsyncMock, dt._selectors.remove_selector_by_path).assert_not_awaited()

    @pytest.mark.asyncio
    async def test_removes_selector_when_present(self) -> None:
        dt = _make_detail_tree(
            cursor_data={"path": "user.id", "value": 1},
            has_selector=True,
        )
        await dt.action_add_select()
        cast(AsyncMock, dt._selectors.remove_selector_by_path).assert_awaited_once_with(
            ".user.id"
        )
        cast(AsyncMock, dt._selectors.add_selector).assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_cursor_is_noop(self) -> None:
        dt = _make_detail_tree(cursor_data=None)
        await dt.action_add_select()
        cast(AsyncMock, dt._selectors.add_selector).assert_not_awaited()
        cast(AsyncMock, dt._selectors.remove_selector_by_path).assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cursor_without_data_is_noop(self) -> None:
        dt = _make_detail_tree()
        node = Mock()
        node.data = None
        dt._cursor_node = node
        await dt.action_add_select()
        cast(AsyncMock, dt._selectors.add_selector).assert_not_awaited()


class TestActionToggleFilterTree:
    def test_flips_flag_false_to_true(self) -> None:
        dt = _make_detail_tree()
        assert dt.show_selected_only is False
        dt.action_toggle_filter_tree()
        assert dt.show_selected_only is True

    def test_flips_flag_true_to_false(self) -> None:
        dt = _make_detail_tree()
        dt.show_selected_only = True
        dt.action_toggle_filter_tree()
        assert dt.show_selected_only is False

    def test_triggers_rebuild(self) -> None:
        dt = _make_detail_tree()
        dt.action_toggle_filter_tree()
        cast(Mock, dt._rebuild_tree).assert_called_once()


def _install_app_mock(dt: DetailTree, monkeypatch: pytest.MonkeyPatch) -> Mock:
    del dt  # unused; param kept for call-site clarity
    app = Mock()
    suspend_ctx = Mock()
    suspend_ctx.__enter__ = Mock(return_value=None)
    suspend_ctx.__exit__ = Mock(return_value=None)
    app.suspend = Mock(return_value=suspend_ctx)
    monkeypatch.setattr(DetailTree, "app", app)
    return app


class TestActionViewValue:
    def test_scalar_writes_txt_file_with_str_value(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        dt = _make_detail_tree(cursor_data={"path": "msg", "value": "hello"})
        _install_app_mock(dt, monkeypatch)
        captured: dict[str, Any] = {}

        def fake_run(argv: list[str], *args: Any, **kwargs: Any) -> Mock:
            del args, kwargs
            captured["argv"] = argv
            captured["content"] = Path(argv[1]).read_text()
            return Mock(returncode=0)

        monkeypatch.setattr("jnav.detail_tree.subprocess.run", fake_run)
        monkeypatch.setenv("EDITOR", "vim")
        dt.action_view_value()
        assert captured["argv"][0] == "vim"
        assert captured["argv"][1].endswith(".txt")
        assert captured["content"] == "hello"
        assert not Path(captured["argv"][1]).exists()

    def test_dict_writes_json_file_with_indented_content(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        value = {"a": 1, "b": [2, 3]}
        dt = _make_detail_tree(cursor_data={"path": "obj", "value": value})
        _install_app_mock(dt, monkeypatch)
        captured: dict[str, Any] = {}

        def fake_run(argv: list[str], *args: Any, **kwargs: Any) -> Mock:
            del args, kwargs
            captured["argv"] = argv
            captured["content"] = Path(argv[1]).read_text()
            return Mock(returncode=0)

        monkeypatch.setattr("jnav.detail_tree.subprocess.run", fake_run)
        monkeypatch.setenv("EDITOR", "nano")
        dt.action_view_value()
        assert captured["argv"][1].endswith(".json")
        assert captured["content"] == json.dumps(value, indent=2, default=str)

    def test_list_writes_json_file(self, monkeypatch: pytest.MonkeyPatch) -> None:
        value = [1, 2, 3]
        dt = _make_detail_tree(cursor_data={"path": "xs", "value": value})
        _install_app_mock(dt, monkeypatch)
        captured: dict[str, Any] = {}

        def fake_run(argv: list[str], *args: Any, **kwargs: Any) -> Mock:
            del args, kwargs
            captured["argv"] = argv
            captured["content"] = Path(argv[1]).read_text()
            return Mock(returncode=0)

        monkeypatch.setattr("jnav.detail_tree.subprocess.run", fake_run)
        monkeypatch.setenv("EDITOR", "vi")
        dt.action_view_value()
        assert captured["argv"][1].endswith(".json")
        assert captured["content"] == json.dumps(value, indent=2)

    def test_falls_back_to_less_when_editor_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        dt = _make_detail_tree(cursor_data={"path": "msg", "value": "x"})
        _install_app_mock(dt, monkeypatch)
        monkeypatch.delenv("EDITOR", raising=False)
        captured: dict[str, Any] = {}

        def fake_run(argv: list[str], *args: Any, **kwargs: Any) -> Mock:
            del args, kwargs
            captured["argv"] = argv
            return Mock(returncode=0)

        monkeypatch.setattr("jnav.detail_tree.subprocess.run", fake_run)
        dt.action_view_value()
        assert captured["argv"][0] == "less"

    def test_suspend_called(self, monkeypatch: pytest.MonkeyPatch) -> None:
        dt = _make_detail_tree(cursor_data={"path": "msg", "value": "x"})
        app = _install_app_mock(dt, monkeypatch)
        monkeypatch.setattr(
            "jnav.detail_tree.subprocess.run", Mock(return_value=Mock(returncode=0))
        )
        monkeypatch.setenv("EDITOR", "vim")
        dt.action_view_value()
        cast(Mock, app.suspend).assert_called_once()

    def test_tempfile_unlinked_even_if_editor_fails(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        dt = _make_detail_tree(cursor_data={"path": "msg", "value": "x"})
        _install_app_mock(dt, monkeypatch)
        monkeypatch.setenv("EDITOR", "vim")
        captured: dict[str, Any] = {}

        def fake_run(argv: list[str], *args: Any, **kwargs: Any) -> Mock:
            del args, kwargs
            captured["path"] = argv[1]
            return Mock(returncode=1)

        monkeypatch.setattr("jnav.detail_tree.subprocess.run", fake_run)
        dt.action_view_value()
        assert not Path(captured["path"]).exists()

    def test_no_cursor_is_noop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        dt = _make_detail_tree(cursor_data=None)
        _install_app_mock(dt, monkeypatch)
        run_mock = Mock()
        monkeypatch.setattr("jnav.detail_tree.subprocess.run", run_mock)
        dt.action_view_value()
        run_mock.assert_not_called()

    def test_cursor_without_data_is_noop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        dt = _make_detail_tree()
        node = Mock()
        node.data = None
        dt._cursor_node = node
        _install_app_mock(dt, monkeypatch)
        run_mock = Mock()
        monkeypatch.setattr("jnav.detail_tree.subprocess.run", run_mock)
        dt.action_view_value()
        run_mock.assert_not_called()


class _PilotApp(App[None]):
    def __init__(self, *, timestamp: TimestampField | None = None) -> None:
        super().__init__()
        self.store = Store()
        self.filter_provider = FilterProvider()
        self.log_model = LogModel(self.store, self.filter_provider)
        self.role_mapper = RoleMapper()
        self.selectors = SelectorProvider()
        self.search = SearchEngine(self.log_model)
        self._initial_timestamp = timestamp

    @override
    def compose(self) -> ComposeResult:
        yield DetailTree(
            "root",
            selectors=self.selectors,
            filters=self.filter_provider,
            search=self.search,
            role_mapper=self.role_mapper,
        )

    async def on_mount(self) -> None:
        await self.log_model.start()
        await self.search.start()
        if self._initial_timestamp is not None:
            await self.role_mapper.set_mapping(
                FieldMapping(timestamp=self._initial_timestamp)
            )


class TestRootLabel:
    @pytest.mark.asyncio
    async def test_index_shown_as_one_based(self) -> None:
        app = _PilotApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            tree = app.query_one(DetailTree)
            entry = make_entry({"level": "INFO"})
            tree.show_entry(entry, 4)
            await pilot.pause()
            assert tree.root.label.plain == "#5"

    @pytest.mark.asyncio
    async def test_timestamp_appended_when_role_mapper_has_one(self) -> None:
        app = _PilotApp(timestamp=TimestampField(path="ts", format="iso8601"))
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            tree = app.query_one(DetailTree)
            entry = make_entry({"ts": "2024-01-01T12:34:56"})
            tree.show_entry(entry, 0)
            await pilot.pause()
            label = tree.root.label.plain
            assert label.startswith("#1 (")
            assert "12:34:56" in label

    @pytest.mark.asyncio
    async def test_empty_timestamp_value_not_rendered(self) -> None:
        app = _PilotApp(timestamp=TimestampField(path="ts", format="iso8601"))
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            tree = app.query_one(DetailTree)
            entry = make_entry({"ts": "", "level": "INFO"})
            tree.show_entry(entry, 0)
            await pilot.pause()
            assert tree.root.label.plain == "#1"

    @pytest.mark.asyncio
    async def test_selected_suffix_present_when_show_selected_only(self) -> None:
        app = _PilotApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            tree = app.query_one(DetailTree)
            entry = make_entry({"level": "INFO"})
            tree.show_selected_only = True
            tree.show_entry(entry, 0)
            await pilot.pause()
            assert tree.root.label.plain == "#1 (selected)"

    @pytest.mark.asyncio
    async def test_no_selected_suffix_by_default(self) -> None:
        app = _PilotApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            tree = app.query_one(DetailTree)
            entry = make_entry({"level": "INFO"})
            tree.show_entry(entry, 0)
            await pilot.pause()
            assert "(selected)" not in tree.root.label.plain


class TestShowSelectedOnly:
    @pytest.mark.asyncio
    async def test_tree_contains_only_selected_paths(self) -> None:
        app = _PilotApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            tree = app.query_one(DetailTree)
            await app.selectors.add_selector(".level")
            entry = make_entry({"level": "INFO", "message": "hi", "extra": 123})
            tree.show_selected_only = True
            tree.show_entry(entry, 0)
            await pilot.pause()
            child_paths = {
                c.data["path"] for c in tree.root.children if c.data is not None
            }
            assert child_paths == {".level"}

    @pytest.mark.asyncio
    async def test_show_selected_only_with_selector_resolving_to_nothing(self) -> None:
        app = _PilotApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            tree = app.query_one(DetailTree)
            await app.selectors.add_selector(".nonexistent")
            entry = make_entry({"level": "INFO"})
            tree.show_selected_only = True
            tree.show_entry(entry, 0)
            await pilot.pause()
            child_paths = {
                c.data["path"] for c in tree.root.children if c.data is not None
            }
            assert child_paths == {".nonexistent"}

    @pytest.mark.asyncio
    async def test_without_show_selected_only_full_entry_rendered(self) -> None:
        app = _PilotApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            tree = app.query_one(DetailTree)
            await app.selectors.add_selector(".level")
            entry = make_entry({"level": "INFO", "message": "hi"})
            tree.show_entry(entry, 0)
            await pilot.pause()
            child_paths = {
                c.data["path"] for c in tree.root.children if c.data is not None
            }
            assert child_paths == {"level", "message"}

    @pytest.mark.asyncio
    async def test_nested_entry_adds_branch_nodes(self) -> None:
        app = _PilotApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            tree = app.query_one(DetailTree)
            entry = make_entry({"user": {"id": 1, "name": "alice"}})
            tree.show_entry(entry, 0)
            await pilot.pause()
            user_nodes = [
                c
                for c in tree.root.children
                if c.data is not None and c.data["path"] == "user"
            ]
            assert len(user_nodes) == 1
            user = user_nodes[0]
            assert not user.allow_expand or len(user.children) > 0
            child_paths = {c.data["path"] for c in user.children if c.data is not None}
            assert {"user.id", "user.name"} <= child_paths


class TestRebuildGuards:
    def test_rebuild_without_entry_is_noop(self) -> None:
        dt = _make_detail_tree()
        del dt._rebuild_tree  # type: ignore[attr-defined]
        clear_mock = Mock()
        dt.clear = clear_mock  # type: ignore[method-assign]
        dt._rebuild_tree()
        clear_mock.assert_not_called()


class TestOnKey:
    @pytest.mark.asyncio
    async def test_on_key_delegates_to_sequence_handler(self) -> None:
        app = _PilotApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            tree = app.query_one(DetailTree)
            entry = make_entry({"level": "INFO"})
            tree.show_entry(entry, 0)
            tree.focus()
            await pilot.pause()
            await pilot.press("f")
            await pilot.pause()
            assert tree._seq_pending is True


class TestRerenderOnSignal:
    @pytest.mark.asyncio
    async def test_selector_change_triggers_rebuild(self) -> None:
        app = _PilotApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            tree = app.query_one(DetailTree)
            entry = make_entry({"level": "INFO", "message": "hi"})
            tree.show_entry(entry, 0)
            await pilot.pause()
            await app.selectors.add_selector(".level")
            await pilot.pause()
            child_paths = {
                c.data["path"] for c in tree.root.children if c.data is not None
            }
            assert child_paths == {"level", "message"}

    @pytest.mark.asyncio
    async def test_search_change_triggers_rebuild(self) -> None:
        app = _PilotApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            tree = app.query_one(DetailTree)
            entry = make_entry({"level": "INFO", "message": "hi"})
            tree.show_entry(entry, 0)
            await pilot.pause()
            rebuild_calls: list[None] = []
            orig = tree._rebuild_tree

            def spy() -> None:
                rebuild_calls.append(None)
                orig()

            tree._rebuild_tree = spy  # type: ignore[method-assign]
            await app.search.set_term("hi")
            await pilot.pause()
            assert len(rebuild_calls) >= 1

    @pytest.mark.asyncio
    async def test_role_mapper_change_triggers_rebuild(self) -> None:
        app = _PilotApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            tree = app.query_one(DetailTree)
            entry = make_entry({"ts": "2024-01-01T12:34:56", "level": "INFO"})
            tree.show_entry(entry, 0)
            await pilot.pause()
            assert tree.root.label.plain == "#1"
            await app.role_mapper.set_mapping(
                FieldMapping(timestamp=TimestampField(path="ts", format="iso8601"))
            )
            await pilot.pause()
            assert "12:34:56" in tree.root.label.plain


class TestTempDirCreated:
    def test_tempdir_created_before_write(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        dt = _make_detail_tree(cursor_data={"path": "msg", "value": "x"})
        _install_app_mock(dt, monkeypatch)
        monkeypatch.setenv("EDITOR", "vim")
        monkeypatch.setattr(
            "jnav.detail_tree.subprocess.run", Mock(return_value=Mock(returncode=0))
        )
        dt.action_view_value()
        assert os.path.isdir("/tmp/jnav")
