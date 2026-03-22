from __future__ import annotations

import json
import os
import subprocess
import tempfile
from typing import TYPE_CHECKING, Any

from textual.binding import Binding, BindingsMap
from textual.events import Key
from textual.message import Message
from textual.widgets import Tree

from .filtering import get_nested, jq_value_literal
from .tree_rendering import TreeNodeData, build_tree

if TYPE_CHECKING:
    from textual import getters
    from textual.app import App


class DetailTree(Tree[TreeNodeData]):
    """Interactive tree view for inspecting a single log entry."""

    if TYPE_CHECKING:
        app = getters.app(App[None])

    _saved_bindings: BindingsMap | None = None

    class FilterRequested(Message):
        def __init__(self, expr: str, combine: str = "and") -> None:
            super().__init__()
            self.expr = expr
            self.combine = combine

    class ColumnRequested(Message):
        def __init__(self, path: str) -> None:
            super().__init__()
            self.path = path

    class SelectedOnlyToggled(Message):
        pass

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

    def on_key(self, event: Key) -> None:
        if self._leader_pending:
            self._leader_pending = False
            event.prevent_default()
            event.stop()
            key = event.key
            if key == "f":
                self._do_filter("and")
            elif key == "o":
                self._do_filter("or")
            elif key == "n":
                self._do_presence_filter("and")
            elif key == "N":
                self._do_presence_filter("or")
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
        self.post_message(self.SelectedOnlyToggled())

    def _do_filter(self, combine: str) -> None:
        node = self.cursor_node
        if node is None or node.data is None:
            return
        path = node.data["path"]
        value = node.data["value"]
        if isinstance(value, (dict, list)):
            return
        expr = f".{path} == {jq_value_literal(value)}"
        self.post_message(self.FilterRequested(expr, combine))

    def _do_presence_filter(self, combine: str) -> None:
        node = self.cursor_node
        if node is None or node.data is None:
            return
        path = node.data["path"]
        self.post_message(self.FilterRequested(f".{path} != null", combine))

    def action_add_select(self) -> None:
        node = self.cursor_node
        if node is None or node.data is None:
            return
        self.post_message(self.ColumnRequested(node.data["path"]))

    def update_entry(
        self,
        entry: dict[str, Any],
        label: str,
        selected: set[str],
        active_columns: list[str],
        search_term: str = "",
        json_paths: set[str] | None = None,
    ) -> None:
        """Populate the tree with an entry's data."""
        self.clear()
        if self.show_selected_only:
            self.root.set_label(f"{label} (selected)")
            filtered = {col: get_nested(entry, col) for col in active_columns}
            build_tree(
                self.root,
                filtered,
                selected=selected,
                search_term=search_term,
                json_paths=json_paths,
            )
        else:
            self.root.set_label(label)
            build_tree(
                self.root,
                entry,
                selected=selected,
                search_term=search_term,
                json_paths=json_paths,
            )
        self.root.expand_all()

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
