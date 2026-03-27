from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, override

from rich.text import Text
from rich.tree import Tree as RichTree
from textual.binding import Binding
from textual.reactive import reactive
from textual.widgets import ListItem, ListView, Static

from .field_manager import FieldManager
from .filtering import get_nested
from .log_model import LogModel
from .search_engine import SearchEngine
from .store import IndexedEntry
from .tree_rendering import build_rich_tree, count_tree_nodes, highlight_text

MAX_CELL_WIDTH = 50

LEVEL_COLORS = {
    "error": "red",
    "fatal": "red bold",
    "critical": "red bold",
    "warn": "yellow",
    "warning": "yellow",
    "info": "green",
    "debug": "cyan",
    "trace": "dim",
}

TS_KEYS = {"timestamp", "ts", "time"}


def _format_timestamp(value: str) -> str:
    try:
        dt = datetime.fromisoformat(value)
        return dt.strftime("%H:%M:%S") + f".{dt.microsecond // 1000:03d}"
    except ValueError, TypeError:
        return str(value)


def _truncate(value: object, width: int = MAX_CELL_WIDTH) -> str:
    s = str(value) if not isinstance(value, str) else value
    if len(s) > width:
        return s[: width - 1] + "\u2026"
    return s


def _entry_summary(
    entry: dict[str, Any],
    columns: list[str],
    col_widths: list[int],
    search_term: str = "",
) -> Text:
    parts: list[str | tuple[str, str]] = []
    for col, width in zip(columns, col_widths):
        val = get_nested(entry, col)
        s = str(val) if val or val == 0 else ""
        if col in TS_KEYS:
            s = _format_timestamp(s)
        s = _truncate(s, width)
        cell = s.ljust(width)
        if col in ("level", "severity"):
            color = LEVEL_COLORS.get(s.strip().lower(), "")
            parts.append((cell, color))
        else:
            parts.append(cell)
        parts.append(" ")
    text = Text.assemble(*parts) if parts else Text("(empty)")
    return highlight_text(text, search_term)


class LogEntryItem(ListItem):
    def __init__(self, entry_index: int, *children: Static) -> None:
        super().__init__(*children)
        self.entry_index = entry_index


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
        padding: 0 1;
        border-left: blank;
    }
    LogListView > LogEntryItem.-highlight {
        color: $foreground;
        background: $background-lighten-2;
        text-style: none;
        border-left: thick $accent;
    }
    LogListView:focus > LogEntryItem.-highlight {
        color: $foreground;
        background: $background-lighten-3;
        text-style: none;
        border-left: thick $accent;
    }
    .inline-tree {
        display: none;
        padding: 0 0 0 4;
        color: $foreground;
    }
    LogListView.expanded-mode .inline-tree {
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
        self._cached_col_widths: dict[str, int] = {}
        self._current_index: int = 0
        self._follow_next_rebuild: bool = False
        self._expanded_mode: bool = True
        self._header: Static | None = None

    async def on_mount(self) -> None:
        await self._model.on_append.subscribe_async(self._on_append)
        await self._model.on_rebuild.subscribe_async(self._on_rebuild)
        await self._fields.on_change.subscribe_async(self._on_refresh)
        await self._search.on_change.subscribe_async(self._on_refresh)

    def on_resize(self) -> None:
        self._refresh_content()

    def set_header(self, header: Static) -> None:
        self._header = header

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
        self._update_cached_col_widths([ie.index for ie in self._model.all()])
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
                delta += count_tree_nodes(data)
        return delta

    def _display_cols(self) -> list[str]:
        return (
            self._fields.base_fields
            if self._expanded_mode
            else self._fields.active_fields
        )

    def _display_cols_and_widths(self) -> tuple[list[str], list[int]]:
        display_cols = self._display_cols()
        col_widths = [
            self._cached_col_widths.get(col, len(col)) for col in display_cols
        ]
        msg_idx = None
        for i, col in enumerate(display_cols):
            if col in ("message", "msg"):
                msg_idx = i
                break
        if msg_idx is not None:
            used = sum(col_widths) + len(col_widths) + 4
            available = self.size.width
            remaining = available - used + col_widths[msg_idx]
            if remaining > col_widths[msg_idx]:
                col_widths[msg_idx] = remaining
        return display_cols, col_widths

    def _update_header(self, display_cols: list[str], col_widths: list[int]) -> None:
        if self._header is None:
            return
        header_parts: list[str | tuple[str, str]] = []
        for col, width in zip(display_cols, col_widths):
            header_parts.append((col.ljust(width), "bold"))
            header_parts.append(" ")
        self._header.update(Text.assemble(*header_parts))

    def _update_cached_col_widths(self, indices: list[int]) -> None:
        for i in indices:
            entry = self._model.get(i).expanded
            for col in self._fields.all_fields:
                val = get_nested(entry, col)
                s = str(val) if val or val == 0 else ""
                if col in TS_KEYS:
                    s = _format_timestamp(s)
                s = _truncate(s, MAX_CELL_WIDTH)
                cur = self._cached_col_widths.get(col, len(col))
                self._cached_col_widths[col] = min(max(cur, len(s)), MAX_CELL_WIDTH)

    def _build_item(self, store_idx: int) -> LogEntryItem:
        display_cols, col_widths = self._display_cols_and_widths()
        parsed = self._model.get(store_idx)
        custom = self._fields.custom_fields_set
        search = self._search.term
        summary = _entry_summary(parsed.expanded, display_cols, col_widths, search)
        if custom:
            filtered = {col: get_nested(parsed.expanded, col) for col in custom}
            rich_tree = build_rich_tree(filtered, custom, search, parsed.expanded_paths)
        else:
            rich_tree = RichTree("", hide_root=True)
        return LogEntryItem(
            store_idx,
            Static(summary),
            Static(rich_tree, classes="inline-tree"),
        )

    async def _on_append(self, new_entries: list[IndexedEntry]) -> None:
        was_at_bottom = (
            len(self._model.visible_indices) > 0
            and (self.index or 0) >= len(self._model.visible_indices) - 1
        )
        was_empty = len(self) == 0

        self._fields.discover(new_entries)

        new_visible = [ie.index for ie in new_entries]
        if not new_visible:
            return

        self._update_cached_col_widths(new_visible)
        with self.app.batch_update():
            for i in new_visible:
                self.append(self._build_item(i))

        if was_at_bottom:
            with self.prevent(ListView.Highlighted):
                self.index = len(self._model.visible_indices) - 1

        if was_empty and new_visible:
            self.index = 0

    async def _on_rebuild(self, _: None) -> None:
        self._rebuild()

    async def _on_refresh(self, _: None) -> None:
        self._refresh_content()

    def _rebuild(self) -> None:
        display_cols, col_widths = self._display_cols_and_widths()
        self._update_header(display_cols, col_widths)

        custom = self._fields.custom_fields_set
        search = self._search.term
        items: list[LogEntryItem] = []
        target_list_index = 0
        for list_idx, i in enumerate(self._model.visible_indices):
            parsed = self._model.get(i)
            summary = _entry_summary(parsed.expanded, display_cols, col_widths, search)
            if custom:
                filtered = {col: get_nested(parsed.expanded, col) for col in custom}
                rich_tree = build_rich_tree(
                    filtered, custom, search, parsed.expanded_paths
                )
            else:
                rich_tree = RichTree("", hide_root=True)
            items.append(
                LogEntryItem(
                    i,
                    Static(summary),
                    Static(rich_tree, classes="inline-tree"),
                )
            )
            if i == self._current_index:
                target_list_index = list_idx

        if self._follow_next_rebuild and items:
            target_list_index = len(items) - 1
            self._follow_next_rebuild = False

        with self.app.batch_update():
            self.clear()
            for item in items:
                self.append(item)

        def _do_set() -> None:
            self.index = target_list_index

        self.call_after_refresh(_do_set)

    def _refresh_content(self) -> None:
        display_cols, col_widths = self._display_cols_and_widths()
        self._update_header(display_cols, col_widths)

        custom = self._fields.custom_fields_set
        search = self._search.term

        for item in self.query(LogEntryItem):
            parsed = self._model.get(item.entry_index)
            children = list(item.query(Static))
            if len(children) >= 2:
                summary = _entry_summary(
                    parsed.expanded, display_cols, col_widths, search
                )
                children[0].update(summary)
                if custom:
                    filtered = {col: get_nested(parsed.expanded, col) for col in custom}
                    children[1].update(
                        build_rich_tree(filtered, custom, search, parsed.expanded_paths)
                    )
                else:
                    children[1].update(RichTree("", hide_root=True))

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
