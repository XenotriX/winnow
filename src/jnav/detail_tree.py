import json
import os
import subprocess
import tempfile
from typing import TYPE_CHECKING, ClassVar, TypedDict

from rich.text import Text
from textual import on
from textual.binding import Binding, BindingType
from textual.events import Key
from textual.widgets import Tree
from textual.widgets.tree import TreeNode

from .filter_provider import FilterProvider
from .filtering import jq_value_literal
from .json_model import JsonValue, children, is_container
from .key_sequences import KeySequence, KeySequenceMixin
from .log_entry_item import format_timestamp
from .node_path import NodePath
from .parsing import ParsedEntry
from .role_mapper import RoleMapper
from .search_engine import SearchEngine
from .selector_provider import Selector, SelectorProvider
from .tree_rendering import TreeStyle, render


class TreeNodeData(TypedDict):
    path: NodePath
    value: JsonValue


def _detail_add_node(
    parent: TreeNode[TreeNodeData],
    label: Text,
    path: NodePath,
    value: JsonValue,
) -> TreeNode[TreeNodeData]:
    data: TreeNodeData = {"path": path, "value": value}
    if is_container(value):
        return parent.add(label, data=data)
    parent.add_leaf(label, data=data)
    return parent


if TYPE_CHECKING:
    from textual import getters
    from textual.app import App


class DetailTree(KeySequenceMixin, Tree[TreeNodeData]):
    COMPONENT_CLASSES: ClassVar[set[str]] = {
        "tree--key",
        "tree--key-selected",
        "tree--value",
        "tree--value-null",
        "tree--json-string",
        "tree--search-highlight",
    }

    DEFAULT_CSS = """
    DetailTree {
        background: $background;
        & > .tree--guides { color: $background-lighten-2; }
        & > .tree--guides-selected { color: $foreground; }
        &:focus {
            background-tint: transparent;
            & > .tree--guides { color: $background-lighten-2; }
            & > .tree--guides-selected { color: $foreground; }
        }
    }
    """

    if TYPE_CHECKING:
        app = getters.app(App[None])

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("j", "cursor_down", show=False),
        Binding("k", "cursor_up", show=False),
        Binding("g", "scroll_home", show=False),
        Binding("G", "scroll_end", show=False),
        Binding("ctrl+d", "page_down", show=False),
        Binding("ctrl+u", "page_up", show=False),
        Binding("s", "add_select", "Select"),
    ]

    SEQUENCES: ClassVar[list[KeySequence]] = [
        KeySequence("ff", "filter_value", "by value"),
        KeySequence("fn", "filter_has", "has field"),
        KeySequence("vo", "toggle_filter_tree", "show selected only"),
        KeySequence("ve", "view_value", "open in editor"),
    ]
    SEQUENCE_GROUPS: ClassVar[dict[str, str]] = {"f": "filter ▸", "v": "view ▸"}

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
        role_mapper: RoleMapper,
        show_selected_only: bool = False,
        collapsed_paths: set[str] | None = None,
        id: str | None = None,
    ) -> None:
        super().__init__(label, id=id)
        self._selectors = selectors
        self._filters = filters
        self._search = search
        self._role_mapper = role_mapper
        self.show_selected_only = show_selected_only
        self._collapsed_paths = collapsed_paths or set()

    @property
    def collapsed_paths(self) -> set[str]:
        return self._collapsed_paths

    def on_focus(self) -> None:
        if self.parent is not None:
            self.parent.add_class("focused")

    def on_blur(self) -> None:
        if self.parent is not None:
            self.parent.remove_class("focused")

    async def on_mount(self) -> None:  # pyright: ignore[reportIncompatibleMethodOverride, reportImplicitOverride]
        await self._selectors.on_change.subscribe_async(self._rerender)
        await self._search.on_change.subscribe_async(self._rerender)
        await self._role_mapper.on_change.subscribe_async(self._rerender)
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

    def _root_label(self, entry: ParsedEntry) -> str:
        label = f"#{self._entry_index + 1}"
        ts_field = self._role_mapper.mapping.timestamp
        if ts_field is not None:
            ts_val = Selector(expression=ts_field.path).resolve(entry.expanded)
            if ts_val not in (None, ""):
                label += f" ({format_timestamp(ts_val, ts_field.format)})"
        if self.show_selected_only:
            label += " (selected)"
        return label

    def _resolve_style(self) -> TreeStyle:
        return TreeStyle(
            key=self.get_component_rich_style("tree--key", partial=True),
            value=self.get_component_rich_style("tree--value", partial=True),
            null=self.get_component_rich_style("tree--value-null", partial=True),
            json_str=self.get_component_rich_style("tree--json-string", partial=True),
            search_hl=self.get_component_rich_style(
                "tree--search-highlight", partial=True
            ),
        )

    def _rebuild_tree(self) -> None:
        if self._entry is None:
            return
        entry = self._entry.expanded

        self.clear()
        self.root.set_label(self._root_label(self._entry))
        root_data: TreeNodeData = {"path": NodePath(), "value": entry}
        self.root.data = root_data
        style = self._resolve_style()
        search_term = self._search.term

        selections: list[tuple[str | int, JsonValue]]
        if self.show_selected_only:
            selections = [
                (sel.expression, value)
                for sel in self._selectors.active_selectors
                if (value := sel.resolve(entry)) is not None
            ]
        else:
            selections = list(children(entry))

        for seg, value in selections:
            render(
                parent=self.root,
                path=NodePath() / seg,
                value=value,
                add_node=_detail_add_node,
                style=style,
                search_term=search_term,
            )

        self.root.expand_all()
        if self._collapsed_paths:
            self._apply_collapse_state(self.root)

    def _apply_collapse_state(self, node: TreeNode[TreeNodeData]) -> None:
        if (
            node is not self.root
            and node.data is not None
            and str(node.data["path"]) in self._collapsed_paths
            and node.is_expanded
        ):
            node.collapse()
            return
        for child in node.children:
            self._apply_collapse_state(child)

    async def on_key(self, event: Key) -> None:
        if await self._handle_sequence_key(event):
            return

    @on(Tree.NodeExpanded)
    def _track_expanded(self, event: Tree.NodeExpanded[TreeNodeData]) -> None:
        if event.node.data is None:
            return
        self._collapsed_paths.discard(str(event.node.data["path"]))

    @on(Tree.NodeCollapsed)
    def _track_collapsed(self, event: Tree.NodeCollapsed[TreeNodeData]) -> None:
        if event.node.data is None:
            return
        self._collapsed_paths.add(str(event.node.data["path"]))

    async def action_filter_value(self) -> None:
        node = self.cursor_node
        if node is None or node.data is None:
            return
        path = node.data["path"]
        value = node.data["value"]
        if isinstance(value, (dict, list)):
            return
        expr = f"{path} == {jq_value_literal(value)}"
        await self._filters.add_filter(expr)

    async def action_filter_has(self) -> None:
        node = self.cursor_node
        if node is None or node.data is None:
            return
        path = node.data["path"]
        await self._filters.add_filter(f"{path} != null")

    def action_toggle_filter_tree(self) -> None:
        self.show_selected_only = not self.show_selected_only
        self._rebuild_tree()

    async def action_add_select(self) -> None:
        node = self.cursor_node
        if node is None or node.data is None:
            return
        selector = str(node.data["path"])
        if self._selectors.has_selector(selector):
            await self._selectors.remove_selector_by_expression(selector)
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
            subprocess.run([editor, path], check=False)
        os.unlink(path)
