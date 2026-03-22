import json
import time
from datetime import datetime
from pathlib import Path

from rich.text import Text
from rich.tree import Tree as RichTree
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    Footer,
    Header,
    Input,
    ListItem,
    ListView,
    OptionList,
    Static,
)
from textual.widgets.option_list import Option
from textual.worker import get_current_worker

from jnav.filter_manager_screen import Filter, FilterManagerScreen

from .detail_tree import DetailTree
from .filtering import (
    apply_combined_filters,
    detect_all_columns,
    flatten_keys,
    get_nested,
    resolve_selected_paths,
)
from .parsing import preprocess_entry
from .tree_rendering import build_rich_tree, count_tree_nodes, highlight_text

PRIORITY_KEYS = ("timestamp", "ts", "time", "level", "severity", "message", "msg")
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


# --- Pure functions ---


def _format_timestamp(value: str) -> str:
    try:
        dt = datetime.fromisoformat(value)
        return dt.strftime("%H:%M:%S") + f".{dt.microsecond // 1000:03d}"
    except ValueError, TypeError:
        return str(value)


def _default_columns(all_columns: list[str]) -> list[str]:
    return [k for k in PRIORITY_KEYS if k in all_columns]


def _truncate(value: object, width: int = MAX_CELL_WIDTH) -> str:
    s = str(value) if not isinstance(value, str) else value
    if len(s) > width:
        return s[: width - 1] + "\u2026"
    return s


def _entry_summary(
    entry: dict,
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


def _compute_col_widths(
    entries: list[dict],
    indices: list[int],
    columns: list[str],
) -> list[int]:
    widths = [len(col) for col in columns]
    for i in indices:
        entry = entries[i]
        for j, col in enumerate(columns):
            val = get_nested(entry, col)
            s = str(val) if val or val == 0 else ""
            if col in TS_KEYS:
                s = _format_timestamp(s)
            s = _truncate(s, MAX_CELL_WIDTH)
            widths[j] = max(widths[j], len(s))
    return [min(w, MAX_CELL_WIDTH) for w in widths]


# --- Modal Screens ---


class ColumnManagerScreen(ModalScreen[None]):
    DEFAULT_CSS = """
    ColumnManagerScreen {
        align: center middle;
    }
    #column-modal {
        width: 60;
        max-width: 90%;
        height: auto;
        max-height: 70%;
        border: solid $surface-lighten-2;
        background: $surface;
        padding: 1 2;
    }
    #column-modal-title {
        text-style: bold;
        padding: 0 0 1 0;
    }
    #column-list {
        height: auto;
        max-height: 14;
        border: none;
    }
    #column-add-input {
        margin: 1 0 0 0;
    }
    #column-add-input.hidden {
        display: none;
    }
    #column-hints {
        color: $text-muted;
        margin: 1 0 0 0;
    }
    """

    BINDINGS = [
        Binding("escape", "maybe_close", "Close", priority=True),
        Binding("a", "add_mode", "Add", show=False),
        Binding("e", "edit_mode", "Edit", show=False),
        Binding("d", "delete", "Delete", show=False),
        Binding("space", "toggle_item", "Toggle", show=False),
    ]

    def __init__(self, custom_columns: list[dict], all_columns: list[str]) -> None:
        super().__init__()
        self.custom_columns = custom_columns
        self.all_columns = all_columns
        self._editing_idx: int | None = None

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static("Fields", id="column-modal-title"),
            OptionList(id="column-list"),
            Input(
                placeholder="field path (e.g. data.role)...",
                id="column-add-input",
                classes="hidden",
            ),
            Static(
                "[b]a[/b]:Add  [b]e[/b]:Edit  [b]space[/b]:Toggle  [b]d[/b]:Delete  [b]esc[/b]:Close",
                id="column-hints",
            ),
            id="column-modal",
        )

    def on_mount(self) -> None:
        self._refresh_list()
        self.query_one("#column-list", OptionList).focus()

    def _refresh_list(self, highlight: int | None = None) -> None:
        ol = self.query_one("#column-list", OptionList)
        ol.clear_options()
        if not self.custom_columns:
            ol.add_option(
                Option(Text(" (no fields selected)", style="dim"), disabled=True)
            )
        else:
            for c in self.custom_columns:
                ol.add_option(_list_option_prompt(c["path"], c["enabled"]))
        if highlight is not None and self.custom_columns:
            ol.highlighted = min(highlight, len(self.custom_columns) - 1)

    def action_toggle_item(self) -> None:
        ol = self.query_one("#column-list", OptionList)
        idx = ol.highlighted
        if idx is not None and idx < len(self.custom_columns):
            self.custom_columns[idx]["enabled"] = not self.custom_columns[idx][
                "enabled"
            ]
            self._refresh_list(idx)

    def action_delete(self) -> None:
        ol = self.query_one("#column-list", OptionList)
        idx = ol.highlighted
        if idx is not None and idx < len(self.custom_columns):
            self.custom_columns.pop(idx)
            self._refresh_list(idx)

    def action_add_mode(self) -> None:
        self._editing_idx = None
        inp = self.query_one("#column-add-input", Input)
        inp.remove_class("hidden")
        inp.value = ""
        inp.focus()

    def action_edit_mode(self) -> None:
        ol = self.query_one("#column-list", OptionList)
        idx = ol.highlighted
        if idx is None or idx >= len(self.custom_columns):
            return
        self._editing_idx = idx
        inp = self.query_one("#column-add-input", Input)
        inp.remove_class("hidden")
        inp.value = self.custom_columns[idx]["path"]
        inp.focus()

    @on(Input.Submitted, "#column-add-input")
    def on_add_submitted(self, event: Input.Submitted) -> None:
        raw = event.value.strip().lstrip(".")
        if raw:
            if self._editing_idx is not None:
                self.custom_columns[self._editing_idx]["path"] = raw
                highlight = self._editing_idx
            else:
                existing = {c["path"] for c in self.custom_columns}
                if raw not in existing:
                    self.custom_columns.append({"path": raw, "enabled": True})
                highlight = len(self.custom_columns) - 1
        else:
            highlight = self._editing_idx
        self._editing_idx = None
        event.input.value = ""
        self.query_one("#column-add-input").add_class("hidden")
        self._refresh_list(highlight)
        self.query_one("#column-list", OptionList).focus()

    def action_maybe_close(self) -> None:
        inp = self.query_one("#column-add-input", Input)
        if not inp.has_class("hidden"):
            self._editing_idx = None
            inp.add_class("hidden")
            inp.value = ""
            self.query_one("#column-list", OptionList).focus()
        else:
            self.dismiss(True)


HELP_TEXT = """\
[b]Global[/b]
  [b]j/k[/b]       Navigate entries (or arrow keys)
  [b]h/l[/b]       Switch focus: list ↔ detail
  [b]Ctrl+D/U[/b]  Half-page scroll down/up
  [b]/[/b]         Search (highlight matches, n/N to navigate)
  [b]n/N[/b]       Next/previous search match
  [b]f[/b]         Manage filters (hide non-matching entries)
  [b]c[/b]         Manage selected fields
  [b]Ctrl+F[/b]    Add text filter (AND)
  [b]Ctrl+S[/b]    Add text filter (OR)
  [b]space[/b]     Pause/unpause filters
  [b]e[/b]         Toggle expanded view
  [b]d[/b]         Toggle detail panel
  [b]r[/b]         Reset all filters, fields, and search
  [b]y[/b]         Copy current entry as JSON
  [b]g[/b]         Jump to first entry
  [b]G[/b]         Jump to last entry
  [b]?[/b]         This help
  [b]q[/b]         Quit

[b]Table / Expanded View[/b]
  [b]Enter[/b]     Open detail panel and inspect entry

[b]Detail Panel[/b]
  [b]f f[/b]       Filter by value (AND)
  [b]f o[/b]       Filter by value (OR)
  [b]f n[/b]       Has field (AND)
  [b]f N[/b]       Has field (OR)
  [b]s[/b]         Select this field for display
  [b]v[/b]         View value in $EDITOR
  [b]t[/b]         Toggle: show only selected fields
  [b]Escape[/b]    Return to main view
"""


class HelpScreen(ModalScreen[None]):
    DEFAULT_CSS = """
    HelpScreen {
        align: center middle;
    }
    #help-modal {
        width: 55;
        max-width: 90%;
        height: auto;
        max-height: 80%;
        border: solid $surface-lighten-2;
        background: $surface;
        padding: 1 2;
    }
    #help-title {
        text-style: bold;
        padding: 0 0 1 0;
    }
    #help-hints {
        color: $text-muted;
        padding: 1 0 0 0;
    }
    """

    BINDINGS = [
        Binding("escape", "close", "Close", priority=True),
        Binding("question_mark", "close", show=False),
    ]

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static("Keybindings", id="help-title"),
            Static(HELP_TEXT),
            Static("[b]esc[/b] or [b]?[/b] to close", id="help-hints"),
            id="help-modal",
        )

    def action_close(self) -> None:
        self.dismiss(True)


class SearchInputScreen(ModalScreen[None]):
    DEFAULT_CSS = """
    SearchInputScreen {
        align: center middle;
    }
    #search-modal {
        width: 50;
        max-width: 90%;
        height: auto;
        border: solid $surface-lighten-2;
        background: $surface;
        padding: 1 2;
    }
    #search-title {
        text-style: bold;
        padding: 0 0 1 0;
    }
    """

    BINDINGS = [
        Binding("escape", "close", "Close", priority=True),
    ]

    def __init__(
        self, title: str = "Search", placeholder: str = "search term..."
    ) -> None:
        super().__init__()
        self._title = title
        self._placeholder = placeholder

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static(self._title, id="search-title"),
            Input(placeholder=self._placeholder, id="search-input"),
            id="search-modal",
        )

    def on_mount(self) -> None:
        self.query_one("#search-input", Input).focus()

    @on(Input.Submitted, "#search-input")
    def on_submitted(self, event: Input.Submitted) -> None:
        term = event.value.strip()
        self.dismiss(term if term else None)

    def action_close(self) -> None:
        self.dismiss(None)


class FilterBar(Static):
    pass


class LogEntryItem(ListItem):
    def __init__(self, entry_index: int, *children: Static) -> None:
        super().__init__(*children)
        self.entry_index = entry_index


# --- Main App ---


def _text_search_expr(term: str) -> str:
    """Build a jq expression for case-insensitive text search across all string fields."""
    escaped = term.lower().replace("\\", "\\\\").replace('"', '\\"')
    return f'[.. | strings] | any(ascii_downcase | contains("{escaped}"))'


def _entry_matches_search(entry: dict, term_lower: str) -> bool:
    def _check(obj: object) -> bool:
        if isinstance(obj, str):
            return term_lower in obj.lower()
        if isinstance(obj, dict):
            return any(_check(v) for v in obj.values())
        if isinstance(obj, list):
            return any(_check(item) for item in obj)
        return term_lower in str(obj).lower()

    return _check(entry)


class JnavApp(App):
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
        entries: list[dict],
        initial_filter: str = "",
        tail_path: str | None = None,
        tail_offset: int = 0,
        state_file: Path | None = None,
    ) -> None:
        super().__init__()
        processed = [preprocess_entry(e) for e in entries]
        self.entries = [p[0] for p in processed]
        self._json_paths: list[set[str]] = [p[1] for p in processed]
        self._original_entries = entries
        self.all_columns: list[str] = detect_all_columns(self.entries)
        self.base_columns: list[str] = _default_columns(self.all_columns)
        self.filters: list[Filter] = []
        self.custom_columns: list[dict] = []
        self.visible_indices: list[int] = list(range(len(entries)))
        self._current_detail_entry: dict | None = None
        self._current_entry_index: int = 0
        self._expanded_mode: bool = True
        self._filters_paused: bool = False
        self._tail_path: str | None = tail_path
        self._tail_offset: int = tail_offset
        self._live: bool = tail_path is not None
        self._follow_next_rebuild: bool = False
        self._search_term: str = ""
        self._search_matches: list[int] = []
        self._search_match_pos: int = -1
        self._state_file: Path | None = state_file
        self._detail_visible_on_load: bool = False
        self._show_selected_only_on_load: bool = False
        self._load_state()
        if initial_filter:
            existing = {f["expr"] for f in self.filters}
            if initial_filter not in existing:
                self.filters.append({"expr": initial_filter, "enabled": True})

    @property
    def active_columns(self) -> list[str]:
        return self.base_columns + [
            c["path"] for c in self.custom_columns if c["enabled"]
        ]

    def _custom_columns_set(self) -> set[str]:
        return {c["path"] for c in self.custom_columns if c["enabled"]}

    def compose(self) -> ComposeResult:
        yield Header()
        yield FilterBar(id="filter-bar")
        yield Horizontal(
            Vertical(
                Static("", id="log-header"),
                ListView(id="log-list"),
            ),
            DetailTree("entry", id="detail-tree"),
            id="content-area",
        )
        yield Footer()

    def on_mount(self) -> None:
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

    def _initial_build(self) -> None:
        self._apply_all_filters()
        self._update_filter_bar()

        if self.entries:
            idx = min(self._current_entry_index, len(self.entries) - 1)
            self._current_entry_index = idx
            self._update_detail(self.entries[idx])

        if self._tail_path:
            self._start_tailing()

    def on_resize(self) -> None:
        self._refresh_list_content()

    # --- State persistence ---

    def _load_state(self) -> None:
        if not self._state_file or not self._state_file.exists():
            return
        try:
            state = json.loads(self._state_file.read_text())
        except json.JSONDecodeError, OSError:
            return
        self.filters = state.get("filters", [])
        self.custom_columns = state.get("custom_columns", [])
        self._expanded_mode = state.get("expanded_mode", False)
        self._filters_paused = state.get("filters_paused", False)
        self._search_term = state.get("search_term", "")
        self._current_entry_index = state.get("entry_index", 0)
        self._detail_visible_on_load = state.get("detail_visible", False)
        self._show_selected_only_on_load = state.get("show_selected_only", False)

    def _save_state(self) -> None:
        if not self._state_file:
            return
        detail = self.query_one("#detail-tree", DetailTree)
        state = {
            "filters": self.filters,
            "custom_columns": self.custom_columns,
            "expanded_mode": self._expanded_mode,
            "filters_paused": self._filters_paused,
            "search_term": self._search_term,
            "entry_index": self._current_entry_index,
            "detail_visible": detail.has_class("visible"),
            "show_selected_only": detail.show_selected_only,
        }
        try:
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            self._state_file.write_text(json.dumps(state))
        except OSError:
            pass

    # --- Filter / column management ---

    def add_filter(
        self, expr: str, label: str | None = None, combine: str = "and"
    ) -> None:
        """Add a new filter. Does not change focus."""
        existing = {f["expr"] for f in self.filters}
        if expr not in existing:
            entry: dict = {"expr": expr, "enabled": True, "combine": combine}
            if label:
                entry["label"] = label
            self.filters.append(entry)
            self._apply_all_filters()
            self._update_filter_bar()
            prefix = "OR filter" if combine == "or" else "Filter"
            self.notify(f"{prefix} added: {label or expr}", timeout=2)

    def add_column(self, path: str) -> None:
        """Add or toggle a custom column. Does not change focus."""
        for c in self.custom_columns:
            if c["path"] == path:
                c["enabled"] = not c["enabled"]
                self._refresh_list_content()
                if self._current_detail_entry:
                    self._update_detail(self._current_detail_entry)
                self._update_filter_bar()
                return
        if path not in self.base_columns:
            self.custom_columns.append({"path": path, "enabled": True})
            self._refresh_list_content()
            if self._current_detail_entry:
                self._update_detail(self._current_detail_entry)
            self._update_filter_bar()

    def _apply_all_filters(self) -> None:
        if self._filters_paused:
            self.visible_indices = list(range(len(self.entries)))
            self._rebuild_list()
            self._recompute_search_matches()
            return
        matched, error = apply_combined_filters(self.filters, self.entries)
        if error:
            self.notify(f"Filter error: {error}", severity="error", timeout=4)
            return
        self.visible_indices = matched
        self._rebuild_list()
        self._recompute_search_matches()

    def _update_filter_bar(self) -> None:
        bar = self.query_one("#filter-bar", FilterBar)
        total = len(self.entries)
        shown = len(self.visible_indices)
        n_filters = sum(1 for f in self.filters if f["enabled"])
        n_cols = sum(1 for c in self.custom_columns if c["enabled"])

        n_or = sum(1 for f in self.filters if f["enabled"] and f.get("combine") == "or")

        parts: list[str] = [f"Showing {shown}/{total}"]
        if n_filters:
            filter_text = f"{n_filters} filter{'s' if n_filters != 1 else ''}"
            if n_or:
                filter_text += f" ({n_or} OR)"
            if self._filters_paused:
                filter_text += " PAUSED"
            parts.append(filter_text)
        if n_cols:
            parts.append(f"{n_cols} field{'s' if n_cols != 1 else ''}")
        if not self._expanded_mode:
            parts.append("Collapsed")

        if self._search_term:
            total = len(self._search_matches)
            pos = self._search_match_pos + 1 if total else 0
            parts.append(f"/{self._search_term} ({pos}/{total})")

        if self._live:
            parts.append("LIVE")

        if not self.filters and not self.custom_columns and not self._search_term:
            parts.append("  /: search  f: filter  ?: help")

        bar.update("  \u2502  ".join(parts))

    # --- Live tailing ---

    @work(thread=True, exclusive=True)
    def _start_tailing(self) -> None:
        path = self._tail_path
        if not path:
            return
        worker = get_current_worker()
        with open(path) as f:
            f.seek(self._tail_offset)
            while not worker.is_cancelled:
                batch: list[dict] = []
                while True:
                    line = f.readline()
                    if not line:
                        break
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                        if isinstance(obj, dict):
                            batch.append(obj)
                    except json.JSONDecodeError:
                        continue
                if batch:
                    self.call_from_thread(self._append_entries, batch)
                time.sleep(0.5)

    def _append_entries(self, new_entries: list[dict]) -> None:
        lv = self.query_one("#log-list", ListView)
        was_at_bottom = (
            lv.index is not None
            and len(self.visible_indices) > 0
            and lv.index >= len(self.visible_indices) - 1
        )
        was_empty = len(self.entries) == 0

        for raw in new_entries:
            expanded, jp = preprocess_entry(raw)
            self.entries.append(expanded)
            self._json_paths.append(jp)
            self._original_entries.append(raw)

        for entry in self.entries[len(self.entries) - len(new_entries) :]:
            for key in flatten_keys(entry):
                if key not in self.all_columns:
                    self.all_columns.append(key)

        if was_empty:
            self.base_columns = _default_columns(self.all_columns)

        if was_at_bottom:
            self._follow_next_rebuild = True

        self._apply_all_filters()
        self._update_filter_bar()

        if was_empty and self.entries:
            self._update_detail(self.entries[0])

    # --- Detail panel ---

    def _update_detail(self, entry: dict) -> None:
        self._current_detail_entry = entry
        idx = self._current_entry_index

        ts_val = None
        for ts_key in TS_KEYS:
            ts_val = get_nested(entry, ts_key)
            if ts_val:
                break
        label = f"#{idx + 1}"
        if ts_val:
            label += f" ({_format_timestamp(str(ts_val))})"

        tree = self.query_one("#detail-tree", DetailTree)
        tree.update_entry(
            entry=entry,
            label=label,
            selected=resolve_selected_paths(self._custom_columns_set(), entry),
            active_columns=self.active_columns,
            search_term=self._search_term,
            json_paths=self._json_paths[idx] if idx < len(self._json_paths) else set(),
        )

    # --- Log list ---

    def _display_cols_and_widths(self) -> tuple[list[str], list[int]]:
        display_cols = self.base_columns if self._expanded_mode else self.active_columns
        col_widths = _compute_col_widths(
            self.entries,
            self.visible_indices,
            display_cols,
        )
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

    def _rebuild_list(self) -> None:
        """Full rebuild: clears and repopulates the list (use when entries change)."""
        display_cols, col_widths = self._display_cols_and_widths()
        self._update_header(display_cols, col_widths)

        lv = self.query_one("#log-list", ListView)

        custom = self._custom_columns_set()
        search = self._search_term
        items: list[LogEntryItem] = []
        target_list_index = 0
        for list_idx, i in enumerate(self.visible_indices):
            entry = self.entries[i]
            jp = self._json_paths[i]
            summary = _entry_summary(entry, display_cols, col_widths, search)
            if custom:
                filtered = {col: get_nested(entry, col) for col in custom}
                rich_tree = build_rich_tree(filtered, custom, search, jp)
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
        custom = self._custom_columns_set()
        search = self._search_term

        for item in lv.query(LogEntryItem):
            entry = self.entries[item.entry_index]
            jp = self._json_paths[item.entry_index]
            children = list(item.query(Static))
            if len(children) >= 2:
                summary = _entry_summary(entry, display_cols, col_widths, search)
                children[0].update(summary)
                if custom:
                    filtered = {col: get_nested(entry, col) for col in custom}
                    children[1].update(build_rich_tree(filtered, custom, search, jp))
                else:
                    children[1].update(RichTree("", hide_root=True))

    # --- Actions ---

    def action_quit(self) -> None:
        self._save_state()
        self.workers.cancel_all()
        self.exit()

    def _focus_main(self) -> None:
        self.query_one("#log-list", ListView).focus()

    def action_open_filters(self) -> None:
        def on_dismiss(result: object) -> None:
            self._apply_all_filters()
            self._update_filter_bar()
            if self._current_detail_entry:
                self._update_detail(self._current_detail_entry)

        self.push_screen(FilterManagerScreen(self.filters), on_dismiss)

    def action_open_columns(self) -> None:
        def on_dismiss(result: object) -> None:
            self._rebuild_list()
            self._update_filter_bar()
            if self._current_detail_entry:
                self._update_detail(self._current_detail_entry)

        self.push_screen(
            ColumnManagerScreen(self.custom_columns, self.all_columns),
            on_dismiss,
        )

    def action_start_search(self) -> None:
        def on_dismiss(term: str | None) -> None:
            if term:
                self._search_term = term
                self._recompute_search_matches()
                self._update_filter_bar()
                self._refresh_list_content()
                if self._current_detail_entry:
                    self._update_detail(self._current_detail_entry)
                if self._search_matches:
                    self._search_match_pos = 0
                    lv = self.query_one("#log-list", ListView)
                    lv.index = self._search_matches[0]
                else:
                    self.notify("No matches found", timeout=2)

        self.push_screen(SearchInputScreen(), on_dismiss)

    def _recompute_search_matches(self) -> None:
        if not self._search_term:
            self._search_matches = []
            self._search_match_pos = -1
            return
        term_lower = self._search_term.lower()
        self._search_matches = [
            list_idx
            for list_idx, entry_idx in enumerate(self.visible_indices)
            if _entry_matches_search(self.entries[entry_idx], term_lower)
        ]
        self._search_match_pos = -1

    def action_search_next(self) -> None:
        if not self._search_matches:
            return
        lv = self.query_one("#log-list", ListView)
        current = lv.index or 0
        for i, match_idx in enumerate(self._search_matches):
            if match_idx > current:
                self._search_match_pos = i
                lv.index = match_idx
                self._update_filter_bar()
                return
        self.notify("No more matches", timeout=1)

    def action_search_prev(self) -> None:
        if not self._search_matches:
            return
        lv = self.query_one("#log-list", ListView)
        current = lv.index or 0
        for i in range(len(self._search_matches) - 1, -1, -1):
            if self._search_matches[i] < current:
                self._search_match_pos = i
                lv.index = self._search_matches[i]
                self._update_filter_bar()
                return
        self.notify("No more matches", timeout=1)

    def action_text_filter(self) -> None:
        def on_dismiss(term: str | None) -> None:
            if term:
                expr = _text_search_expr(term)
                self.add_filter(expr, label=f"text: {term}")

        self.push_screen(SearchInputScreen("Text Filter (AND)"), on_dismiss)

    def action_text_filter_or(self) -> None:
        def on_dismiss(term: str | None) -> None:
            if term:
                expr = _text_search_expr(term)
                self.add_filter(expr, label=f"text: {term}", combine="or")

        self.push_screen(SearchInputScreen("Text Filter (OR)"), on_dismiss)

    def action_toggle_expanded(self) -> None:
        lv = self.query_one("#log-list", ListView)
        hi = lv.index or 0

        # Compute scroll delta: sum of tree line counts for items above highlighted
        custom = self._custom_columns_set()
        delta = 0
        if custom:
            for list_idx, vis_idx in enumerate(self.visible_indices):
                if list_idx >= hi:
                    break
                entry = self.entries[vis_idx]
                data = {col: get_nested(entry, col) for col in custom}
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
            if self._current_detail_entry:
                self._update_detail(self._current_detail_entry)

    def action_inspect(self) -> None:
        """Open detail panel and focus it (Enter key)."""
        lv = self.query_one("#log-list", ListView)
        if self.focused != lv:
            return
        detail = self.query_one("#detail-tree", DetailTree)
        if not detail.has_class("visible"):
            detail.add_class("visible")
        if self._current_detail_entry:
            self._update_detail(self._current_detail_entry)
        detail.focus()

    def action_reset(self) -> None:
        self.filters.clear()
        self.custom_columns.clear()
        self._search_term = ""
        self._search_matches = []
        self._search_match_pos = -1
        self._apply_all_filters()
        self._update_filter_bar()
        if self._current_detail_entry:
            self._update_detail(self._current_detail_entry)
        self.notify("Filters and fields cleared", timeout=2)

    def action_copy_entry(self) -> None:
        if self._current_detail_entry:
            original = self._original_entries[self._current_entry_index]
            text = json.dumps(original, indent=2, default=str)
            self.copy_to_clipboard(text)
            self.notify("Entry copied to clipboard", timeout=2)

    def action_cursor_down(self) -> None:
        lv = self.query_one("#log-list", ListView)
        if lv.index is not None and lv.index < len(self.visible_indices) - 1:
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
        max_idx = len(self.visible_indices) - 1
        if lv.index is not None:
            lv.index = min(lv.index + half, max_idx)

    def action_scroll_half_up(self) -> None:
        lv = self.query_one("#log-list", ListView)
        half = max(1, lv.size.height // 2)
        if lv.index is not None:
            lv.index = max(lv.index - half, 0)

    def action_toggle_filters_pause(self) -> None:
        if not self.filters:
            return
        self._filters_paused = not self._filters_paused
        self._apply_all_filters()
        self._update_filter_bar()
        state = "paused" if self._filters_paused else "active"
        self.notify(f"Filters {state}", timeout=2)

    def action_jump_top(self) -> None:
        self.query_one("#log-list", ListView).index = 0

    def action_jump_bottom(self) -> None:
        self.query_one("#log-list", ListView).index = len(self.visible_indices) - 1

    def action_show_help(self) -> None:
        self.push_screen(HelpScreen())

    def action_escape(self) -> None:
        tree = self.query_one("#detail-tree", DetailTree)
        if self.focused == tree:
            self._focus_main()
        elif self._search_term:
            self._search_term = ""
            self._search_matches = []
            self._search_match_pos = -1
            self._update_filter_bar()
            self._refresh_list_content()
            if self._current_detail_entry:
                self._update_detail(self._current_detail_entry)

    @on(ListView.Highlighted, "#log-list")
    def on_log_highlighted(self, event: ListView.Highlighted) -> None:
        if event.item and isinstance(event.item, LogEntryItem):
            self._current_entry_index = event.item.entry_index
            self._update_detail(self.entries[self._current_entry_index])

    @on(ListView.Selected, "#log-list")
    def on_log_selected(self, event: ListView.Selected) -> None:
        self.action_inspect()

    @on(DetailTree.FilterRequested)
    def on_filter_requested(self, event: DetailTree.FilterRequested) -> None:
        self.add_filter(event.expr, combine=event.combine)

    @on(DetailTree.ColumnRequested)
    def on_column_requested(self, event: DetailTree.ColumnRequested) -> None:
        self.add_column(event.path)

    @on(DetailTree.SelectedOnlyToggled)
    def on_selected_only_toggled(self, event: DetailTree.SelectedOnlyToggled) -> None:
        if self._current_detail_entry is not None:
            self._update_detail(self._current_detail_entry)
