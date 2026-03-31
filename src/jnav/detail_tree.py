from __future__ import annotations

import json
import os
import subprocess
import tempfile
from typing import TYPE_CHECKING, Literal, TypedDict

from rich.text import Text
from textual.binding import Binding, BindingsMap
from textual.events import Key
from textual.widgets import Tree
from textual.widgets.tree import TreeNode

from .field_manager import FieldManager
from .filter_provider import FilterProvider
from .filtering import get_nested, jq_value_literal, resolve_selected_paths
from .parsing import ParsedEntry
from .search_engine import SearchEngine
from .tree_rendering import walk_tree


class TreeNodeData(TypedDict):
    path: str
    value: object


def _build_tree(
    node: TreeNode[TreeNodeData],
    value: object,
    path: str = "",
    selected: set[str] | None = None,
    search_term: str = "",
    json_paths: set[str] | None = None,
) -> None:
    sel = selected or set()

    def add_branch(label: Text, children_value: object, child_path: str, orig_value: object) -> None:
        branch = node.add(label, data={"path": child_path, "value": orig_value})
        _build_tree(branch, children_value, child_path, sel, search_term, json_paths)

    def add_leaf(label: Text, child_path: str, orig_value: object) -> None:
        node.add_leaf(label, data={"path": child_path, "value": orig_value})

    walk_tree(
        value=value,
        path=path,
        selected=sel,
        add_branch=add_branch,
        add_leaf=add_leaf,
        search_term=search_term,
        json_paths=json_paths,
    )

if TYPE_CHECKING:
    from textual import getters
    from textual.app import App

TS_KEYS = {"timestamp", "ts", "time"}


def _format_timestamp(value: str) -> str:
    from datetime import datetime

    try:
        dt = datetime.fromisoformat(value)
        return dt.strftime("%H:%M:%S") + f".{dt.microsecond // 1000:03d}"
    except ValueError, TypeError:
        return str(value)


class DetailTree(Tree[TreeNodeData]):

    if TYPE_CHECKING:
        app = getters.app(App[None])

    _saved_bindings: BindingsMap | None = None

    BINDINGS = [
        Binding("j", "cursor_down", show=False),
        Binding("k", "cursor_up", show=False),
        Binding("g", "scroll_home", show=False),
        Binding("G", "scroll_end", show=False),
        Binding("ctrl+d", "page_down", show=False),
        Binding("ctrl+u", "page_up", show=False),
        Binding("s", "add_select", "Add field"),
        Binding("t", "toggle_filter_tree", "Selected only"),
        Binding("v", "view_value", "View"),
    ]

    _LEADER_BINDINGS = [
        Binding("f", "leader_filter_and", "Filter AND"),
        Binding("o", "leader_filter_or", "Filter OR"),
        Binding("n", "leader_has_and", "Has field AND"),
        Binding("N", "leader_has_or", "Has field OR"),
        Binding("escape", "leader_cancel", "Cancel", show=False),
    ]

    show_selected_only: bool = False
    _leader_pending: bool = False
    _entry: ParsedEntry | None = None
    _entry_index: int = 0

    def __init__(
        self,
        label: str,
        *,
        fields: FieldManager,
        filters: FilterProvider,
        search: SearchEngine,
        id: str | None = None,
    ) -> None:
        super().__init__(label, id=id)
        self._fields = fields
        self._filters = filters
        self._search = search

    async def on_mount(self) -> None:  # pyright: ignore[reportIncompatibleMethodOverride, reportImplicitOverride]
        await self._fields.on_change.subscribe_async(self._rerender)
        await self._search.on_change.subscribe_async(self._rerender)

    async def _rerender(self, _: None) -> None:
        self._rebuild_tree()

    @property
    def entry(self) -> ParsedEntry | None:
        return self._entry

    def show_entry(self, parsed: ParsedEntry, index: int) -> None:
        self._entry = parsed
        self._entry_index = index
        self._rebuild_tree()

    def _rebuild_tree(self) -> None:
        if self._entry is None:
            return
        entry = self._entry.expanded
        selected = resolve_selected_paths(self._fields.custom_fields_set, entry)

        ts_val = None
        for ts_key in TS_KEYS:
            ts_val = get_nested(entry, ts_key)
            if ts_val:
                break
        label = f"#{self._entry_index + 1}"
        if ts_val:
            label += f" ({_format_timestamp(str(ts_val))})"
        if self.show_selected_only:
            label += " (selected)"

        self.clear()
        self.root.set_label(label)
        if self.show_selected_only:
            filtered = {col: get_nested(entry, col) for col in self._fields.active_fields}
            _build_tree(
                self.root,
                filtered,
                selected=selected,
                search_term=self._search.term,
                json_paths=self._entry.expanded_paths,
            )
        else:
            _build_tree(
                self.root,
                entry,
                selected=selected,
                search_term=self._search.term,
                json_paths=self._entry.expanded_paths,
            )
        self.root.expand_all()

    def action_leader_filter_and(self) -> None:
        pass

    def action_leader_filter_or(self) -> None:
        pass

    def action_leader_has_and(self) -> None:
        pass

    def action_leader_has_or(self) -> None:
        pass

    def action_leader_cancel(self) -> None:
        pass

    async def on_key(self, event: Key) -> None:
        if self._leader_pending:
            self._leader_pending = False
            event.prevent_default()
            event.stop()
            key = event.key
            if key == "f":
                await self._do_filter("and")
            elif key == "o":
                await self._do_filter("or")
            elif key == "n":
                await self._do_presence_filter("and")
            elif key == "N":
                await self._do_presence_filter("or")
            self._restore_bindings()
            return
        if event.key == "f":
            self._leader_pending = True
            event.prevent_default()
            event.stop()
            self._show_leader_bindings()

    def _show_leader_bindings(self) -> None:
        self._saved_bindings = self._bindings
        self._bindings = BindingsMap(self._LEADER_BINDINGS)
        self.refresh_bindings()

    def _restore_bindings(self) -> None:
        if self._saved_bindings is not None:
            self._bindings = self._saved_bindings
            del self._saved_bindings
        self.refresh_bindings()

    def action_toggle_filter_tree(self) -> None:
        self.show_selected_only = not self.show_selected_only
        self._rebuild_tree()

    async def _do_filter(self, combine: Literal["and", "or"]) -> None:
        node = self.cursor_node
        if node is None or node.data is None:
            return
        path = node.data["path"]
        value = node.data["value"]
        if isinstance(value, (dict, list)):
            return
        expr = f".{path} == {jq_value_literal(value)}"
        await self._filters.add_filter(expr, combine=combine)

    async def _do_presence_filter(self, combine: Literal["and", "or"]) -> None:
        node = self.cursor_node
        if node is None or node.data is None:
            return
        path = node.data["path"]
        await self._filters.add_filter(f".{path} != null", combine=combine)

    async def action_add_select(self) -> None:
        node = self.cursor_node
        if node is None or node.data is None:
            return
        await self._fields.add_field(node.data["path"])

    def action_view_value(self) -> None:
        node = self.cursor_node
        if node is None or node.data is None:
            return
        value = node.data["value"]
        if isinstance(value, (dict, list)):
            content = json.dumps(value, indent=2, default=str)
            suffix = ".json"
        else:
            content = str(value)
            suffix = ".txt"
        editor = os.environ.get("EDITOR", "less")
        tmpdir = "/tmp/jnav"
        os.makedirs(tmpdir, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=suffix,
            prefix="jnav_",
            dir=tmpdir,
            delete=False,
        ) as f:
            f.write(content)
            path = f.name
        with self.app.suspend():
            subprocess.run([editor, path])
        os.unlink(path)
