import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, override

from rich.text import Text
from rich.tree import Tree as RichTree
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, ListItem, ListView, Static

from jnav.field_manager import FieldManager
from jnav.field_manager_screen import FieldManagerScreen
from jnav.filter_manager_screen import FilterManagerScreen
from jnav.filter_provider import FilterProvider
from jnav.help_screen import HelpScreen
from jnav.log_model import LogModel
from jnav.search_engine import SearchEngine
from jnav.search_input_screen import SearchInputScreen
from jnav.store import IndexedEntry

from .detail_tree import DetailTree
from .filtering import get_nested, text_search_expr
from .tree_rendering import build_rich_tree, count_tree_nodes, highlight_text

logger = logging.getLogger(__name__)

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


class FilterBar(Static):
    pass


class LogEntryItem(ListItem):
    def __init__(self, entry_index: int, *children: Static) -> None:
        super().__init__(*children)
        self.entry_index = entry_index


class JnavApp(App[None]):
    CSS = """
    #filter-bar {
        height: 1;
        padding: 0 1;
        color: $text-muted;
    }
    #content-area {
        height: 1fr;
    }
    #log-header {
        height: 1;
        padding: 0 1;
        text-style: bold;
        color: $text-muted;
    }
    #log-list {
        height: 1fr;
    }
    #log-list LogEntryItem {
        padding: 0 1;
        border-left: blank;
    }
    #log-list > LogEntryItem.-highlight {
        color: $foreground;
        background: $background-lighten-2;
        text-style: none;
        border-left: thick $accent;
    }
    #log-list:focus > LogEntryItem.-highlight {
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
    .expanded-mode .inline-tree {
        display: block;
    }
    #detail-tree {
        width: 40%;
        padding: 0 0 0 2;
        display: none;
    }
    #detail-tree.visible {
        display: block;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("slash", "start_search", "Search", key_display="/"),
        Binding("f", "open_filters", "Filter"),
        Binding("c", "open_columns", "Fields"),
        Binding("ctrl+f", "text_filter", "Text filter"),
        Binding("ctrl+s", "text_filter_or", "Text OR"),
        Binding("e", "toggle_expanded", "Expand"),
        Binding("d", "toggle_detail", "Detail"),
        Binding("r", "reset", "Reset"),
        Binding("y", "copy_entry", "Copy"),
        Binding("j", "cursor_down", show=False),
        Binding("k", "cursor_up", show=False),
        Binding("h", "focus_list", show=False),
        Binding("l", "focus_detail", show=False),
        Binding("ctrl+d", "scroll_half_down", show=False),
        Binding("ctrl+u", "scroll_half_up", show=False),
        Binding("n", "search_next", show=False),
        Binding("N", "search_prev", show=False),
        Binding("space", "toggle_filters_pause", show=False),
        Binding("g", "jump_top", show=False),
        Binding("G", "jump_bottom", show=False),
        Binding("question_mark", "show_help", "?", key_display="?"),
        Binding("escape", "escape", show=False),
        Binding("enter", "inspect", "Inspect", show=False),
    ]

    def __init__(
        self,
        model: LogModel,
        filter_provider: FilterProvider,
        fields: FieldManager,
        search: SearchEngine,
        state_file: Path | None = None,
    ) -> None:
        super().__init__()
        self._model = model
        self._filter_provider: FilterProvider = filter_provider
        self._fields: FieldManager = fields
        self._search: SearchEngine = search
        self._cached_col_widths: dict[str, int] = {}
        self._current_entry_index: int = 0
        self._expanded_mode: bool = True
        self._follow_next_rebuild: bool = False
        self._search_pos: int = -1
        self._state_file: Path | None = state_file
        self._detail_visible_on_load: bool = False
        self._show_selected_only_on_load: bool = False

    @override
    def compose(self) -> ComposeResult:
        yield Header()
        yield FilterBar(id="filter-bar")
        yield Horizontal(
            Vertical(
                Static("", id="log-header"),
                ListView(id="log-list"),
            ),
            DetailTree(
                "entry",
                fields=self._fields,
                filters=self._filter_provider,
                search=self._search,
                id="detail-tree",
            ),
            id="content-area",
        )
        yield Footer()

    async def on_mount(self) -> None:
        await self._load_state()

        await self._model.on_append.subscribe_async(self._append_entries)
        await self._model.on_rebuild.subscribe_async(self._on_rebuild)
        await self._search.on_change.subscribe_async(self._on_search_changed)
        await self._fields.on_change.subscribe_async(self._on_fields_changed)

        lv = self.query_one("#log-list", ListView)
        lv.focus()

        if self._expanded_mode:
            self.query_one("#content-area").add_class("expanded-mode")

        if self._detail_visible_on_load:
            self.query_one("#detail-tree", DetailTree).add_class("visible")

        detail_tree = self.query_one("#detail-tree", DetailTree)
        detail_tree.show_selected_only = self._show_selected_only_on_load

        # Defer initial build until after layout so ListView has a real width
        self.call_after_refresh(self._initial_build)

    async def _initial_build(self) -> None:
        self._fields.discover(self._model.all())
        await self._on_rebuild(None)

    def on_resize(self) -> None:
        self._refresh_list_content()

    async def _load_state(self) -> None:
        if not self._state_file or not self._state_file.exists():
            return
        try:
            state = json.loads(self._state_file.read_text())
        except json.JSONDecodeError, OSError:
            return
        await self._filter_provider.set_filters(state.get("filters", []))
        await self._fields.set_custom_fields(state.get("custom_fields", []))
        self._expanded_mode = state.get("expanded_mode", False)
        await self._model.set_filtering_enabled(not state.get("filters_paused", False))
        await self._search.set_term(state.get("search_term", ""))
        self._current_entry_index = state.get("entry_index", 0)
        self._detail_visible_on_load = state.get("detail_visible", False)
        self._show_selected_only_on_load = state.get("show_selected_only", False)

    def _save_state(self) -> None:
        if not self._state_file:
            return
        detail = self.query_one("#detail-tree", DetailTree)
        state = {
            "filters": self._filter_provider.get_filters(),
            "custom_fields": self._fields.custom_fields,
            "expanded_mode": self._expanded_mode,
            "filters_paused": self._model.filtering_enabled is False,
            "search_term": self._search.term,
            "entry_index": self._current_entry_index,
            "detail_visible": detail.has_class("visible"),
            "show_selected_only": detail.show_selected_only,
        }
        try:
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            self._state_file.write_text(json.dumps(state))
        except OSError:
            pass

    async def _on_rebuild(self, _: None) -> None:
        await self._rebuild_list()
        self._update_filter_bar()

    async def _on_search_changed(self, _: None) -> None:
        self._search_pos = -1
        self._refresh_list_content()
        self._update_filter_bar()

    async def _on_fields_changed(self, _: None) -> None:
        self._refresh_list_content()
        self._update_filter_bar()

    def _update_filter_bar(self) -> None:
        bar = self.query_one("#filter-bar", FilterBar)
        total = self._model.count()
        shown = len(self._model.visible_indices)
        n_filters = sum(1 for f in self._filter_provider.get_filters() if f["enabled"])
        n_cols = sum(1 for c in self._fields.custom_fields if c["enabled"])

        n_or = sum(
            1
            for f in self._filter_provider.get_filters()
            if f["enabled"] and f.get("combine") == "or"
        )

        parts: list[str] = [f"Showing {shown}/{total}"]
        if n_filters:
            filter_text = f"{n_filters} filter{'s' if n_filters != 1 else ''}"
            if n_or:
                filter_text += f" ({n_or} OR)"
            if not self._model.filtering_enabled:
                filter_text += " PAUSED"
            parts.append(filter_text)
        if n_cols:
            parts.append(f"{n_cols} field{'s' if n_cols != 1 else ''}")
        if not self._expanded_mode:
            parts.append("Collapsed")

        if self._search.term:
            total = len(self._search.matches)
            pos = self._search_pos + 1 if total else 0
            parts.append(f"/{self._search.term} ({pos}/{total})")

        if (
            not self._filter_provider.get_filters()
            and not self._fields.custom_fields
            and not self._search.term
        ):
            parts.append("  /: search  f: filter  ?: help")

        bar.update("  \u2502  ".join(parts))

    async def _append_entries(self, new_entries: list[IndexedEntry]) -> None:
        lv = self.query_one("#log-list", ListView)
        was_at_bottom = (
            lv.index is not None
            and len(self._model.visible_indices) > 0
            and lv.index >= len(self._model.visible_indices) - 1
        )
        was_empty = len(lv) == 0

        self._fields.discover(new_entries)

        new_visible = [ie.index for ie in new_entries]

        if not new_visible:
            self._update_filter_bar()
            return

        display_cols = (
            self._fields.base_fields
            if self._expanded_mode
            else self._fields.active_fields
        )
        self._update_cached_col_widths(new_visible)
        col_widths = self._get_col_widths(display_cols)
        custom = self._fields.custom_fields_set
        search = self._search.term
        with self.batch_update():
            for i in new_visible:
                parsed = self._model.get(i)
                summary = _entry_summary(
                    parsed.expanded, display_cols, col_widths, search
                )
                if custom:
                    filtered = {col: get_nested(parsed.expanded, col) for col in custom}
                    rich_tree = build_rich_tree(
                        filtered, custom, search, parsed.expanded_paths
                    )
                else:
                    rich_tree = RichTree("", hide_root=True)
                lv.append(
                    LogEntryItem(
                        i,
                        Static(summary),
                        Static(rich_tree, classes="inline-tree"),
                    )
                )

        if was_at_bottom:
            with self.prevent(ListView.Highlighted):
                lv.index = len(self._model.visible_indices) - 1

        self._update_filter_bar()

        if was_empty and new_visible:
            self.query_one("#detail-tree", DetailTree).show_entry(
                self._model.get(new_visible[0]), new_visible[0]
            )

    def _update_cached_col_widths(self, indices: list[int]) -> None:
        """Update cached column widths with new entries."""
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

    def _get_col_widths(self, columns: list[str]) -> list[int]:
        """Get column widths from cache."""
        return [self._cached_col_widths.get(col, len(col)) for col in columns]

    def _display_cols_and_widths(self) -> tuple[list[str], list[int]]:
        display_cols = (
            self._fields.base_fields
            if self._expanded_mode
            else self._fields.active_fields
        )
        col_widths = self._get_col_widths(display_cols)
        # Expand message/msg column to fill available width
        msg_idx = None
        for i, col in enumerate(display_cols):
            if col in ("message", "msg"):
                msg_idx = i
                break
        if msg_idx is not None:
            lv = self.query_one("#log-list", ListView)
            # 2 for padding, 1 space separator per column, 2 for border
            used = sum(col_widths) + len(col_widths) + 4
            available = lv.size.width
            remaining = available - used + col_widths[msg_idx]
            if remaining > col_widths[msg_idx]:
                col_widths[msg_idx] = remaining
        return display_cols, col_widths

    def _update_header(self, display_cols: list[str], col_widths: list[int]) -> None:
        header_parts: list[str | tuple[str, str]] = []
        for col, width in zip(display_cols, col_widths):
            header_parts.append((col.ljust(width), "bold"))
            header_parts.append(" ")
        self.query_one("#log-header", Static).update(Text.assemble(*header_parts))

    async def _rebuild_list(self) -> None:
        """Full rebuild: clears and repopulates the list (use when entries change)."""
        display_cols, col_widths = self._display_cols_and_widths()
        self._update_header(display_cols, col_widths)

        lv = self.query_one("#log-list", ListView)

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
            if i == self._current_entry_index:
                target_list_index = list_idx

        if self._follow_next_rebuild and items:
            target_list_index = len(items) - 1
            self._follow_next_rebuild = False

        with self.batch_update():
            lv.clear()
            for item in items:
                lv.append(item)

        def _do_set() -> None:
            lv.index = target_list_index

        self.call_after_refresh(_do_set)

    def _refresh_list_content(self) -> None:
        """Light refresh: updates content of existing items in place (no flicker)."""
        display_cols, col_widths = self._display_cols_and_widths()
        self._update_header(display_cols, col_widths)

        lv = self.query_one("#log-list", ListView)
        custom = self._fields.custom_fields_set
        search = self._search.term

        for item in lv.query(LogEntryItem):
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

    @override
    async def action_quit(self) -> None:
        self._save_state()
        self.workers.cancel_all()
        self.exit()

    def _focus_main(self) -> None:
        self.query_one("#log-list", ListView).focus()

    def action_open_filters(self) -> None:
        self.push_screen(FilterManagerScreen(self._filter_provider))

    def action_open_columns(self) -> None:
        self.push_screen(FieldManagerScreen(self._fields))

    def action_start_search(self) -> None:
        async def on_dismiss(term: str | None) -> None:
            if not term:
                return
            await self._search.set_term(term)
            if self._search.matches:
                self._search_pos = 0
                self._jump_to_store_index(self._search.matches[0])
            else:
                self.notify("No matches found", timeout=2)

        self.push_screen(SearchInputScreen(), on_dismiss)

    def _current_store_index(self) -> int:
        lv = self.query_one("#log-list", ListView)
        list_idx = lv.index or 0
        visible = self._model.visible_indices
        if list_idx < len(visible):
            return visible[list_idx]
        return 0

    def _jump_to_store_index(self, store_idx: int) -> None:
        visible = self._model.visible_indices
        try:
            lv = self.query_one("#log-list", ListView)
            lv.index = visible.index(store_idx)
        except ValueError:
            pass

    def action_search_next(self) -> None:
        if not self._search.matches:
            return
        current = self._current_store_index()
        for i, store_idx in enumerate(self._search.matches):
            if store_idx > current:
                self._search_pos = i
                self._jump_to_store_index(store_idx)
                self._update_filter_bar()
                return
        self.notify("No more matches", timeout=1)

    def action_search_prev(self) -> None:
        if not self._search.matches:
            return
        current = self._current_store_index()
        for i in range(len(self._search.matches) - 1, -1, -1):
            if self._search.matches[i] < current:
                self._search_pos = i
                self._jump_to_store_index(self._search.matches[i])
                self._update_filter_bar()
                return
        self.notify("No more matches", timeout=1)

    def action_text_filter(self) -> None:
        async def on_dismiss(term: str | None) -> None:
            if term:
                expr = text_search_expr(term)
                await self._filter_provider.add_filter(expr, label=f"text: {term}")

        self.push_screen(SearchInputScreen("Text Filter (AND)"), on_dismiss)

    def action_text_filter_or(self) -> None:
        async def on_dismiss(term: str | None) -> None:
            if term:
                expr = text_search_expr(term)
                await self._filter_provider.add_filter(
                    expr, label=f"text: {term}", combine="or"
                )

        self.push_screen(SearchInputScreen("Text Filter (OR)"), on_dismiss)

    def action_toggle_expanded(self) -> None:
        lv = self.query_one("#log-list", ListView)
        hi = lv.index or 0

        # Compute scroll delta: sum of tree line counts for items above highlighted
        custom = self._fields.custom_fields_set
        delta = 0
        if custom:
            for list_idx, vis_idx in enumerate(self._model.visible_indices):
                if list_idx >= hi:
                    break
                parsed = self._model.get(vis_idx)
                data = {col: get_nested(parsed.expanded, col) for col in custom}
                delta += count_tree_nodes(data)

        # Toggle mode
        self._expanded_mode = not self._expanded_mode
        content = self.query_one("#content-area")
        if self._expanded_mode:
            content.add_class("expanded-mode")
            new_y = lv.scroll_y + delta
        else:
            content.remove_class("expanded-mode")
            new_y = max(0, lv.scroll_y - delta)

        self._refresh_list_content()
        self._update_filter_bar()

        # Set scroll immediately for flicker-free first frame
        lv.set_scroll(None, new_y)

        # After relayout, set scroll properly (updates scrollbar + validates against new max_scroll_y)
        def _fix_scroll():
            lv.scroll_to(y=new_y, animate=False, immediate=True, force=True)

        lv.call_after_refresh(_fix_scroll)

    def action_toggle_detail(self) -> None:
        detail = self.query_one("#detail-tree", DetailTree)
        if detail.has_class("visible"):
            detail.remove_class("visible")
            self._focus_main()
        else:
            detail.add_class("visible")

    def action_inspect(self) -> None:
        """Open detail panel and focus it (Enter key)."""
        lv = self.query_one("#log-list", ListView)
        if self.focused != lv:
            return
        detail = self.query_one("#detail-tree", DetailTree)
        if not detail.has_class("visible"):
            detail.add_class("visible")
        detail.focus()

    async def action_reset(self) -> None:
        await self._fields.clear_custom_fields()
        await self._search.clear()
        await self._filter_provider.clear_filters()
        self.notify("Filters and fields cleared", timeout=2)

    def action_copy_entry(self) -> None:
        tree = self.query_one("#detail-tree", DetailTree)
        if tree.entry:
            text = json.dumps(tree.entry.raw, indent=2, default=str)
            self.copy_to_clipboard(text)
            self.notify("Entry copied to clipboard", timeout=2)

    def action_cursor_down(self) -> None:
        lv = self.query_one("#log-list", ListView)
        if lv.index is not None and lv.index < len(self._model.visible_indices) - 1:
            lv.index += 1

    def action_cursor_up(self) -> None:
        lv = self.query_one("#log-list", ListView)
        if lv.index is not None and lv.index > 0:
            lv.index -= 1

    def action_focus_list(self) -> None:
        detail = self.query_one("#detail-tree", DetailTree)
        if detail.has_class("visible"):
            self.query_one("#log-list", ListView).focus()

    def action_focus_detail(self) -> None:
        detail = self.query_one("#detail-tree", DetailTree)
        if detail.has_class("visible"):
            detail.focus()

    def action_scroll_half_down(self) -> None:
        lv = self.query_one("#log-list", ListView)
        half = max(1, lv.size.height // 2)
        max_idx = len(self._model.visible_indices) - 1
        if lv.index is not None:
            lv.index = min(lv.index + half, max_idx)

    def action_scroll_half_up(self) -> None:
        lv = self.query_one("#log-list", ListView)
        half = max(1, lv.size.height // 2)
        if lv.index is not None:
            lv.index = max(lv.index - half, 0)

    async def action_toggle_filters_pause(self) -> None:
        if not self._filter_provider.get_filters():
            return
        await self._model.set_filtering_enabled(not self._model.filtering_enabled)
        state = "active" if self._model.filtering_enabled else "paused"
        self.notify(f"Filters {state}", timeout=2)

    def action_jump_top(self) -> None:
        self.query_one("#log-list", ListView).index = 0

    def action_jump_bottom(self) -> None:
        self.query_one("#log-list", ListView).index = (
            len(self._model.visible_indices) - 1
        )

    def action_show_help(self) -> None:
        self.push_screen(HelpScreen())

    async def action_escape(self) -> None:
        tree = self.query_one("#detail-tree", DetailTree)
        if self.focused == tree:
            self._focus_main()
        elif self._search.active:
            await self._search.clear()

    @on(ListView.Highlighted, "#log-list")
    def on_log_highlighted(self, event: ListView.Highlighted) -> None:
        if event.item and isinstance(event.item, LogEntryItem):
            self._current_entry_index = event.item.entry_index
            self.query_one("#detail-tree", DetailTree).show_entry(
                self._model.get(self._current_entry_index), self._current_entry_index
            )

    @on(ListView.Selected, "#log-list")
    def on_log_selected(self, event: ListView.Selected) -> None:
        del event  # unused
        self.action_inspect()

