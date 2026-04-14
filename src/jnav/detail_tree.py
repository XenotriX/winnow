import json
import os
import subprocess
import tempfile
from typing import TYPE_CHECKING, TypedDict

from rich.text import Text
from textual.binding import Binding
from textual.events import Key
from textual.widgets import Tree
from textual.widgets.tree import TreeNode

from .filter_provider import FilterProvider
from .key_sequences import KeySequence, KeySequenceMixin
from .filtering import get_nested, jq_value_literal, resolve_selected_paths
from .parsing import ParsedEntry
from .search_engine import SearchEngine
from .selector_provider import SelectorProvider
from .tree_rendering import TreeBuildVisitor, walk_tree


class TreeNodeData(TypedDict):
    path: str
    value: object


def _detail_add_branch(
    parent: TreeNode[TreeNodeData],
    label: Text,
    path: str,
    value: object,
) -> TreeNode[TreeNodeData]:
    return parent.add(label, data={"path": path, "value": value})


def _detail_add_leaf(
    parent: TreeNode[TreeNodeData],
    label: Text,
    path: str,
    value: object,
) -> None:
    parent.add_leaf(label, data={"path": path, "value": value})


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


class DetailTree(KeySequenceMixin, Tree[TreeNodeData]):
    COMPONENT_CLASSES = {
        "tree--key",
        "tree--key-selected",
        "tree--value",
        "tree--value-null",
        "tree--json-string",
        "tree--search-highlight",
    }

    DEFAULT_CSS = ""

    if TYPE_CHECKING:
        app = getters.app(App[None])

    BINDINGS = [
        Binding("j", "cursor_down", show=False),
        Binding("k", "cursor_up", show=False),
        Binding("g", "scroll_home", show=False),
        Binding("G", "scroll_end", show=False),
        Binding("ctrl+d", "page_down", show=False),
        Binding("ctrl+u", "page_up", show=False),
        Binding("s", "add_select", "Select"),
    ]

    SEQUENCES = [
        KeySequence("ff", "filter_value", "by value"),
        KeySequence("fn", "filter_has", "has field"),
        KeySequence("vo", "toggle_filter_tree", "show selected only"),
        KeySequence("ve", "view_value", "open in editor"),
    ]
    SEQUENCE_GROUPS = {"f": "filter ▸", "v": "view ▸"}

    show_selected_only: bool = False
    _entry: ParsedEntry | None = None
    _entry_index: int = 0

    def __init__(
        self,
        label: str,
        *,
        selectors: SelectorProvider,
        filters: FilterProvider,
        search: SearchEngine,
        id: str | None = None,
    ) -> None:
        super().__init__(label, id=id)
        self._selectors = selectors
        self._filters = filters
        self._search = search

    def on_focus(self) -> None:
        if self.parent is not None:
            self.parent.add_class("focused")

    def on_blur(self) -> None:
        if self.parent is not None:
            self.parent.remove_class("focused")

    async def on_mount(self) -> None:  # pyright: ignore[reportIncompatibleMethodOverride, reportImplicitOverride]
        await self._selectors.on_change.subscribe_async(self._rerender)
        await self._search.on_change.subscribe_async(self._rerender)
        self.app.theme_changed_signal.subscribe(self, lambda _: self._rebuild_tree())

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
        selected = resolve_selected_paths(self._selectors.active_selectors, entry)

        ts_val = None
        for ts_key in TS_KEYS:
            ts_val = entry.get(ts_key)
            if ts_val:
                break
        label = f"#{self._entry_index + 1}"
        if ts_val:
            label += f" ({_format_timestamp(str(ts_val))})"
        if self.show_selected_only:
            label += " (selected)"

        self.clear()
        self.root.set_label(label)
        data = (
            {s: get_nested(entry, s) for s in self._selectors.active_selectors}
            if self.show_selected_only
            else entry
        )
        visitor = TreeBuildVisitor(
            root=self.root,
            add_branch=_detail_add_branch,
            add_leaf=_detail_add_leaf,
            selected=selected,
            key_style=self.get_component_rich_style("tree--key", partial=True),
            selected_style=self.get_component_rich_style(
                "tree--key-selected", partial=True
            ),
            value_style=self.get_component_rich_style("tree--value", partial=True),
            value_null_style=self.get_component_rich_style(
                "tree--value-null", partial=True
            ),
            json_string_style=self.get_component_rich_style(
                "tree--json-string", partial=True
            ),
            search_highlight_style=self.get_component_rich_style(
                "tree--search-highlight", partial=True
            ),
            search_term=self._search.term,
        )
        walk_tree(
            value=data, path="", visitor=visitor, json_paths=self._entry.expanded_paths
        )
        self.root.expand_all()

    async def on_key(self, event: Key) -> None:
        if await self._handle_sequence_key(event):
            return

    async def action_filter_value(self) -> None:
        node = self.cursor_node
        if node is None or node.data is None:
            return
        path = node.data["path"]
        value = node.data["value"]
        if isinstance(value, (dict, list)):
            return
        expr = f".{path} == {jq_value_literal(value)}"
        await self._filters.add_filter(expr)

    async def action_filter_has(self) -> None:
        node = self.cursor_node
        if node is None or node.data is None:
            return
        path = node.data["path"]
        await self._filters.add_filter(f".{path} != null")

    def action_toggle_filter_tree(self) -> None:
        self.show_selected_only = not self.show_selected_only
        self._rebuild_tree()

    async def action_add_select(self) -> None:
        node = self.cursor_node
        if node is None or node.data is None:
            return
        selector = "." + node.data["path"]
        if self._selectors.has_selector(selector):
            await self._selectors.remove_selector_by_path(selector)
        else:
            await self._selectors.add_selector(selector)

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
