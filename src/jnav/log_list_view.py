from __future__ import annotations

from typing import TYPE_CHECKING, override

from rich.text import Text
from textual.binding import Binding
from textual.reactive import reactive
from textual.widgets import ListView, Static

from .field_manager import FieldManager
from .filtering import get_nested
from .log_entry_item import LogEntryItem
from .log_model import LogModel
from .search_engine import SearchEngine
from .store import IndexedEntry
from .tree_rendering import walk_tree


def _count_tree_nodes(value: object) -> int:
    count = 0

    def add_branch(
        label: Text, children_value: object, child_path: str, orig_value: object
    ) -> None:
        del label, child_path, orig_value  # unused
        nonlocal count
        count += 1 + _count_tree_nodes(children_value)

    def add_leaf(label: Text, child_path: str, orig_value: object) -> None:
        del label, child_path, orig_value  # unused
        nonlocal count
        count += 1

    walk_tree(
        value=value,
        path="",
        selected=set(),
        add_branch=add_branch,
        add_leaf=add_leaf,
    )
    return count


if TYPE_CHECKING:
    from textual import getters
    from textual.app import App


class LogListView(ListView):
    index: reactive[int | None] | int | None

    if TYPE_CHECKING:
        app = getters.app(App[None])

    BINDINGS = [
        Binding("j", "cursor_down", show=False),
        Binding("k", "cursor_up", show=False),
        Binding("ctrl+d", "scroll_half_down", show=False),
        Binding("ctrl+u", "scroll_half_up", show=False),
        Binding("g", "jump_top", show=False),
        Binding("G", "jump_bottom", show=False),
        Binding("e", "toggle_expanded", "Expand"),
    ]

    DEFAULT_CSS = """
    LogListView {
        height: 1fr;
    }
    LogListView LogEntryItem {
    }
    LogListView LogEntryItem > EntrySummary {
        padding: 0 1;
        background: $surface-lighten-1;
    }
    LogListView LogEntryItem.-highlight > EntrySummary {
        background: #2a3340;
    }
    LogListView LogEntryItem.-highlight > InlineTree {
        background: #242c38;
    }
    LogListView.expanded-mode InlineTree {
        display: block;
    }
    """

    def __init__(
        self,
        *,
        model: LogModel,
        fields: FieldManager,
        search: SearchEngine,
        id: str | None = None,
    ) -> None:
        super().__init__(id=id)
        self._model = model
        self._fields = fields
        self._search = search
        self._current_index: int = 0
        self._follow_next_rebuild: bool = False
        self._expanded_mode: bool = True
        self._chrome: tuple[Static, ...] = ()

    async def on_mount(self) -> None:
        await self._model.on_append.subscribe_async(self._on_append)
        await self._model.on_rebuild.subscribe_async(self._on_rebuild)
        await self._fields.on_change.subscribe_async(self._on_refresh)
        await self._search.on_change.subscribe_async(self._on_refresh)

    def on_focus(self) -> None:
        for w in self._chrome:
            w.add_class("focused")

    def on_blur(self) -> None:
        for w in self._chrome:
            w.remove_class("focused")

    def set_chrome(self, *widgets: Static) -> None:
        self._chrome = widgets
        if self.has_focus:
            self.on_focus()

    def set_expanded_mode(self, expanded: bool) -> None:
        hi = self.index or 0
        delta = self._compute_expanded_scroll_delta(hi)

        self._expanded_mode = expanded
        if expanded:
            self.add_class("expanded-mode")
            new_y = self.scroll_y + delta
        else:
            self.remove_class("expanded-mode")
            new_y = max(0, self.scroll_y - delta)

        self._refresh_content()
        self.set_scroll(None, new_y)

        def _fix_scroll() -> None:
            self.scroll_to(y=new_y, animate=False, immediate=True, force=True)

        self.call_after_refresh(_fix_scroll)

    def set_current_index(self, index: int) -> None:
        self._current_index = index

    @property
    def expanded_mode(self) -> bool:
        return self._expanded_mode

    def initial_build(self) -> None:
        self._fields.discover(self._model.all())
        self._rebuild()

    def current_index(self) -> int:
        list_idx = self.index or 0
        visible = self._model.visible_indices
        if list_idx < len(visible):
            return visible[list_idx]
        return 0

    def jump_to_index(self, store_idx: int) -> None:
        visible = self._model.visible_indices
        try:
            self.index = visible.index(store_idx)
        except ValueError:
            pass

    def _compute_expanded_scroll_delta(self, highlighted_index: int) -> int:
        custom = self._fields.custom_fields_set
        delta = 0
        if custom:
            for list_idx, vis_idx in enumerate(self._model.visible_indices):
                if list_idx >= highlighted_index:
                    break
                parsed = self._model.get(vis_idx)
                data = {col: get_nested(parsed.expanded, col) for col in custom}
                delta += _count_tree_nodes(data)
        return delta

    async def _on_append(self, new_entries: list[IndexedEntry]) -> None:
        was_at_bottom = (
            len(self._model.visible_indices) > 0
            and (self.index or 0) >= len(self._model.visible_indices) - 1
        )
        was_empty = len(self) == 0

        self._fields.discover(new_entries)

        if not new_entries:
            return

        with self.app.batch_update():
            for ie in new_entries:
                self.append(LogEntryItem(ie))

        self.call_after_refresh(self._refresh_content)

        if was_at_bottom:
            with self.prevent(ListView.Highlighted):
                self.index = len(self._model.visible_indices) - 1

        if was_empty and new_entries:
            self.index = 0

    async def _on_rebuild(self, _: None) -> None:
        self._rebuild()

    async def _on_refresh(self, _: None) -> None:
        self._refresh_content()

    def _rebuild(self) -> None:
        items: list[LogEntryItem] = []
        target_list_index = 0
        for list_idx, i in enumerate(self._model.visible_indices):
            ie = IndexedEntry(i, self._model.get(i))
            items.append(LogEntryItem(ie))
            if i == self._current_index:
                target_list_index = list_idx

        if self._follow_next_rebuild and items:
            target_list_index = len(items) - 1
            self._follow_next_rebuild = False

        with self.app.batch_update():
            self.clear()
            for item in items:
                self.append(item)

        def _after_rebuild() -> None:
            self.index = target_list_index
            self._refresh_content()

        self.call_after_refresh(_after_rebuild)

    def _refresh_content(self) -> None:
        custom = self._fields.custom_fields_set
        search = self._search.term

        for item in self.query(LogEntryItem):
            item.refresh_content(custom, search, self._expanded_mode)

    def _visible_count(self) -> int:
        return len(self._model.visible_indices)

    @override
    def action_cursor_down(self) -> None:
        idx = self.index or 0
        if idx < self._visible_count() - 1:
            self.index = idx + 1

    @override
    def action_cursor_up(self) -> None:
        idx = self.index or 0
        if idx > 0:
            self.index = idx - 1

    def action_scroll_half_down(self) -> None:
        half = max(1, self.size.height // 2)
        idx = self.index or 0
        self.index = min(idx + half, self._visible_count() - 1)

    def action_scroll_half_up(self) -> None:
        half = max(1, self.size.height // 2)
        idx = self.index or 0
        self.index = max(idx - half, 0)

    def action_jump_top(self) -> None:
        self.index = 0

    def action_jump_bottom(self) -> None:
        count = self._visible_count()
        if count > 0:
            self.index = count - 1

    def action_toggle_expanded(self) -> None:
        self.set_expanded_mode(not self._expanded_mode)
