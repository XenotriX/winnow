from __future__ import annotations

import json
import re
import sys
from collections import OrderedDict
from datetime import datetime

import click
import jq
from rich.text import Text
from rich.tree import Tree as RichTree
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingsMap
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    Footer, Header, Input, ListItem, ListView,
    OptionList, Static, Tree,
)
from textual.widgets.option_list import Option
from textual.widgets.tree import TreeNode


PRIORITY_KEYS = ("timestamp", "ts", "time", "level", "severity", "message", "msg")
MAX_CELL_WIDTH = 50

LEVEL_COLORS = {
    "error": "red",
    "fatal": "red bold",
    "critical": "red bold",
    "warn": "yellow",
    "warning": "yellow",
    "info": "green",
    "debug": "dim",
    "trace": "dim",
}

TS_KEYS = {"timestamp", "ts", "time"}


# --- Pure functions ---

def apply_jq_filter(
    expression: str, entries: list[dict],
) -> tuple[list[int], str | None]:
    try:
        prog = jq.compile(expression)
    except ValueError as e:
        return [], str(e)
    matched = []
    for i, entry in enumerate(entries):
        try:
            results = prog.input_value(entry).all()
            if any(_is_truthy(r) for r in results):
                matched.append(i)
        except Exception:
            continue
    return matched, None


def apply_combined_filters(
    filters: list[dict], entries: list[dict],
) -> tuple[list[int], str | None]:
    """Apply all enabled filters (AND group unioned with OR group)."""
    enabled = [f for f in filters if f["enabled"]]
    if not enabled:
        return list(range(len(entries))), None
    and_exprs = [f["expr"] for f in enabled if f.get("combine", "and") == "and"]
    or_exprs = [f["expr"] for f in enabled if f.get("combine") == "or"]
    parts = []
    if and_exprs:
        parts.append(" and ".join(f"({e})" for e in and_exprs))
    if or_exprs:
        parts.append(" or ".join(f"({e})" for e in or_exprs))
    if not parts:
        return list(range(len(entries))), None
    combined = " or ".join(f"({p})" for p in parts)
    return apply_jq_filter(combined, entries)


_ASSIGNMENT_RE = re.compile(r'(?<![=!<>])=(?!=)')


def _check_filter_warning(expression: str) -> str | None:
    if _ASSIGNMENT_RE.search(expression):
        return "Did you mean '==' instead of '='? ('=' is jq's update operator)"
    return None


def _is_truthy(value: object) -> bool:
    if value is None or value is False:
        return False
    if isinstance(value, (list, dict, str)) and len(value) == 0:
        return False
    return True


_jq_cache: dict[str, jq._Program] = {}


def _get_nested(entry: dict, path: str) -> object:
    # Fast path: simple dotted keys like "data.role"
    if "[" not in path:
        obj = entry
        for part in path.split("."):
            if isinstance(obj, dict):
                obj = obj.get(part, "")
            else:
                return ""
        return obj
    # Complex paths with array indices: use jq with compilation cache
    prog = _jq_cache.get(path)
    if prog is None:
        jq_path = "." + path if not path.startswith(".") else path
        try:
            prog = jq.compile(jq_path)
        except ValueError:
            return ""
        _jq_cache[path] = prog
    try:
        result = prog.input_value(entry).first()
        return result if result is not None else ""
    except Exception:
        return ""
    return obj


def _flatten_keys(obj: dict, prefix: str = "") -> list[str]:
    keys = []
    for k, v in obj.items():
        full = f"{prefix}{k}"
        if isinstance(v, dict):
            for sub_k in v:
                keys.append(f"{full}.{sub_k}")
        else:
            keys.append(full)
    return keys


def _detect_all_columns(entries: list[dict]) -> list[str]:
    seen: OrderedDict[str, None] = OrderedDict()
    for entry in entries:
        for key in _flatten_keys(entry):
            if key not in seen:
                seen[key] = None
    return list(seen)


def _default_columns(all_columns: list[str]) -> list[str]:
    return [k for k in PRIORITY_KEYS if k in all_columns]


def _format_timestamp(value: str) -> str:
    try:
        dt = datetime.fromisoformat(value)
        return dt.strftime("%H:%M:%S") + f".{dt.microsecond // 1000:03d}"
    except (ValueError, TypeError):
        return str(value)


def _truncate(value: object, width: int = MAX_CELL_WIDTH) -> str:
    s = str(value) if not isinstance(value, str) else value
    if len(s) > width:
        return s[: width - 1] + "\u2026"
    return s


def _style_level(value: str) -> Text:
    color = LEVEL_COLORS.get(value.lower(), "")
    return Text(value, style=color) if color else Text(value)


def _jq_value_literal(value: object) -> str:
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(value)


def _sorted_keys(d: dict) -> list[str]:
    priority = [k for k in PRIORITY_KEYS if k in d]
    rest = [k for k in d if k not in priority]
    return priority + rest


def _text_search_expr(term: str) -> str:
    """Build a jq expression for case-insensitive text search across all string fields."""
    escaped = term.lower().replace("\\", "\\\\").replace('"', '\\"')
    return f'[.. | strings] | any(ascii_downcase | contains("{escaped}"))'


# --- Textual Tree builder (interactive, for detail panel) ---

SELECTED_STYLE = "bold bright_green underline"


def _node_label(
    key: str, value: object, path: str, custom_selected: set[str],
) -> Text:
    is_custom = path in custom_selected
    key_style = SELECTED_STYLE if is_custom else "bold"
    if isinstance(value, dict):
        return Text.assemble((key, key_style), ": ", ("{}", "dim"))
    elif isinstance(value, list):
        return Text.assemble((key, key_style), ": ", (f"[{len(value)} items]", "dim"))
    else:
        display = _truncate(str(value), 60)
        return Text.assemble((key, key_style), ": ", (display, ""))


def _build_tree(
    node: TreeNode, value: object, path: str = "",
    selected: set[str] | None = None,
) -> None:
    sel = selected or set()
    if isinstance(value, dict):
        for k in _sorted_keys(value):
            v = value[k]
            child_path = f"{path}.{k}" if path else k
            if isinstance(v, (dict, list)):
                branch = node.add(
                    _node_label(k, v, child_path, sel),
                    data={"path": child_path, "value": v},
                )
                _build_tree(branch, v, child_path, sel)
            else:
                node.add_leaf(
                    _node_label(k, v, child_path, sel),
                    data={"path": child_path, "value": v},
                )
    elif isinstance(value, list):
        for i, item in enumerate(value):
            child_path = f"{path}[{i}]"
            if isinstance(item, (dict, list)):
                branch = node.add(
                    Text.assemble((f"[{i}]", "dim")),
                    data={"path": child_path, "value": item},
                )
                _build_tree(branch, item, child_path, sel)
            else:
                display = _truncate(str(item), 60)
                node.add_leaf(
                    Text.assemble((f"[{i}]", "dim"), ": ", (display, "")),
                    data={"path": child_path, "value": item},
                )


def _count_tree_nodes(value: object) -> int:
    """Count nodes in the Rich tree for a value (matches _populate_rich_tree structure)."""
    if isinstance(value, dict):
        count = 0
        for v in value.values():
            count += 1
            if isinstance(v, (dict, list)):
                count += _count_tree_nodes(v)
        return count
    elif isinstance(value, list):
        count = 0
        for item in value:
            count += 1
            if isinstance(item, (dict, list)):
                count += _count_tree_nodes(item)
        return count
    return 0


# --- Rich Tree builder (static, for inline expanded view) ---

def _build_rich_tree(entry: dict, custom_selected: set[str]) -> RichTree:
    tree = RichTree("", guide_style="dim", hide_root=True)
    _populate_rich_tree(tree, entry, "", custom_selected)
    return tree


def _populate_rich_tree(
    node: RichTree, value: object, path: str, custom_selected: set[str],
) -> None:
    if isinstance(value, dict):
        for k in _sorted_keys(value):
            v = value[k]
            child_path = f"{path}.{k}" if path else k
            is_custom = child_path in custom_selected
            key_style = SELECTED_STYLE if is_custom else "bold"
            if isinstance(v, dict):
                branch = node.add(Text.assemble((k, key_style)))
                _populate_rich_tree(branch, v, child_path, custom_selected)
            elif isinstance(v, list):
                branch = node.add(
                    Text.assemble((k, key_style), (f" [{len(v)}]", "dim")),
                )
                _populate_rich_tree(branch, v, child_path, custom_selected)
            else:
                display = _truncate(str(v), 60)
                node.add(
                    Text.assemble((k, key_style), (": ", "dim"), (display, "")),
                )
    elif isinstance(value, list):
        for i, item in enumerate(value):
            child_path = f"{path}[{i}]"
            if isinstance(item, (dict, list)):
                branch = node.add(Text(f"[{i}]", style="dim"))
                _populate_rich_tree(branch, item, child_path, custom_selected)
            else:
                display = _truncate(str(item), 60)
                node.add(
                    Text.assemble((f"[{i}]", "dim"), (": ", ""), (display, "")),
                )


def _entry_summary(entry: dict, columns: list[str], col_widths: list[int]) -> Text:
    parts: list[str | tuple[str, str]] = []
    for col, width in zip(columns, col_widths):
        val = _get_nested(entry, col)
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
    return Text.assemble(*parts) if parts else Text("(empty)")


def _compute_col_widths(
    entries: list[dict], indices: list[int], columns: list[str],
) -> list[int]:
    widths = [len(col) for col in columns]
    for i in indices:
        entry = entries[i]
        for j, col in enumerate(columns):
            val = _get_nested(entry, col)
            s = str(val) if val or val == 0 else ""
            if col in TS_KEYS:
                s = _format_timestamp(s)
            s = _truncate(s, MAX_CELL_WIDTH)
            widths[j] = max(widths[j], len(s))
    return [min(w, MAX_CELL_WIDTH) for w in widths]


# --- Modal Screens ---

def _list_option_prompt(label: str, enabled: bool, combine: str = "and") -> Text:
    marker = "\u2713" if enabled else " "
    style = "" if enabled else "dim"
    prefix = "OR " if combine == "or" else "   "
    return Text.assemble((prefix, "italic" if combine == "or" else "dim"), (f"{marker} ", style), (label, style))


class FilterManagerScreen(ModalScreen):
    DEFAULT_CSS = """
    FilterManagerScreen {
        align: center middle;
    }
    #filter-modal {
        width: 70;
        max-width: 90%;
        height: auto;
        max-height: 70%;
        border: solid $surface-lighten-2;
        background: $surface;
        padding: 1 2;
    }
    #filter-modal-title {
        text-style: bold;
        padding: 0 0 1 0;
    }
    #filter-list {
        height: auto;
        max-height: 14;
        border: none;
    }
    #filter-add-input {
        margin: 1 0 0 0;
    }
    #filter-add-input.hidden {
        display: none;
    }
    #filter-hints {
        color: $text-muted;
        margin: 1 0 0 0;
    }
    """

    BINDINGS = [
        Binding("escape", "maybe_close", "Close", priority=True),
        Binding("a", "add_mode", "Add", show=False),
        Binding("d", "delete", "Delete", show=False),
        Binding("space", "toggle_item", "Toggle", show=False),
        Binding("o", "toggle_combine", "AND/OR", show=False),
    ]

    def __init__(self, filters: list[dict]) -> None:
        super().__init__()
        self.filters = filters

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static("Filters", id="filter-modal-title"),
            OptionList(id="filter-list"),
            Input(placeholder="jq expression...", id="filter-add-input", classes="hidden"),
            Static(
                "[b]a[/b]:Add  [b]space[/b]:Toggle  [b]o[/b]:AND/OR  [b]d[/b]:Delete  [b]esc[/b]:Close",
                id="filter-hints",
            ),
            id="filter-modal",
        )

    def on_mount(self) -> None:
        self._refresh_list()
        self.query_one("#filter-list", OptionList).focus()

    def _refresh_list(self, highlight: int | None = None) -> None:
        ol = self.query_one("#filter-list", OptionList)
        ol.clear_options()
        if not self.filters:
            ol.add_option(Option(Text(" (no filters)", style="dim"), disabled=True))
        else:
            for f in self.filters:
                ol.add_option(_list_option_prompt(f.get("label") or f["expr"], f["enabled"], f.get("combine", "and")))
        if highlight is not None and self.filters:
            ol.highlighted = min(highlight, len(self.filters) - 1)

    def action_toggle_item(self) -> None:
        ol = self.query_one("#filter-list", OptionList)
        idx = ol.highlighted
        if idx is not None and idx < len(self.filters):
            self.filters[idx]["enabled"] = not self.filters[idx]["enabled"]
            self._refresh_list(idx)

    def action_toggle_combine(self) -> None:
        ol = self.query_one("#filter-list", OptionList)
        idx = ol.highlighted
        if idx is not None and idx < len(self.filters):
            current = self.filters[idx].get("combine", "and")
            self.filters[idx]["combine"] = "or" if current == "and" else "and"
            self._refresh_list(idx)

    def action_delete(self) -> None:
        ol = self.query_one("#filter-list", OptionList)
        idx = ol.highlighted
        if idx is not None and idx < len(self.filters):
            self.filters.pop(idx)
            self._refresh_list(idx)

    def action_add_mode(self) -> None:
        inp = self.query_one("#filter-add-input", Input)
        inp.remove_class("hidden")
        inp.value = ""
        inp.focus()

    @on(Input.Submitted, "#filter-add-input")
    def on_add_submitted(self, event: Input.Submitted) -> None:
        expr = event.value.strip()
        if expr:
            warning = _check_filter_warning(expr)
            self.filters.append({"expr": expr, "enabled": True})
            if warning:
                self.notify(warning, severity="warning", timeout=3)
        event.input.value = ""
        self.query_one("#filter-add-input").add_class("hidden")
        self._refresh_list(len(self.filters) - 1 if expr else None)
        self.query_one("#filter-list", OptionList).focus()

    def action_maybe_close(self) -> None:
        inp = self.query_one("#filter-add-input", Input)
        if not inp.has_class("hidden"):
            inp.add_class("hidden")
            inp.value = ""
            self.query_one("#filter-list", OptionList).focus()
        else:
            self.dismiss(True)


class ColumnManagerScreen(ModalScreen):
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
        Binding("d", "delete", "Delete", show=False),
        Binding("space", "toggle_item", "Toggle", show=False),
    ]

    def __init__(self, custom_columns: list[dict], all_columns: list[str]) -> None:
        super().__init__()
        self.custom_columns = custom_columns
        self.all_columns = all_columns

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
                "[b]a[/b]:Add  [b]space[/b]:Toggle  [b]d[/b]:Delete  [b]esc[/b]:Close",
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
            ol.add_option(Option(Text(" (no fields selected)", style="dim"), disabled=True))
        else:
            for c in self.custom_columns:
                ol.add_option(_list_option_prompt(c["path"], c["enabled"]))
        if highlight is not None and self.custom_columns:
            ol.highlighted = min(highlight, len(self.custom_columns) - 1)

    def action_toggle_item(self) -> None:
        ol = self.query_one("#column-list", OptionList)
        idx = ol.highlighted
        if idx is not None and idx < len(self.custom_columns):
            self.custom_columns[idx]["enabled"] = not self.custom_columns[idx]["enabled"]
            self._refresh_list(idx)

    def action_delete(self) -> None:
        ol = self.query_one("#column-list", OptionList)
        idx = ol.highlighted
        if idx is not None and idx < len(self.custom_columns):
            self.custom_columns.pop(idx)
            self._refresh_list(idx)

    def action_add_mode(self) -> None:
        inp = self.query_one("#column-add-input", Input)
        inp.remove_class("hidden")
        inp.value = ""
        inp.focus()

    @on(Input.Submitted, "#column-add-input")
    def on_add_submitted(self, event: Input.Submitted) -> None:
        raw = event.value.strip().lstrip(".")
        if raw:
            existing = {c["path"] for c in self.custom_columns}
            if raw not in existing:
                self.custom_columns.append({"path": raw, "enabled": True})
        event.input.value = ""
        self.query_one("#column-add-input").add_class("hidden")
        self._refresh_list(len(self.custom_columns) - 1 if raw else None)
        self.query_one("#column-list", OptionList).focus()

    def action_maybe_close(self) -> None:
        inp = self.query_one("#column-add-input", Input)
        if not inp.has_class("hidden"):
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
  [b]f[/b]         Manage filters
  [b]c[/b]         Manage selected fields
  [b]Ctrl+F[/b]    Text filter (AND)
  [b]Ctrl+S[/b]    Text filter (OR)
  [b]space[/b]     Pause/unpause filters
  [b]e[/b]         Toggle expanded view
  [b]d[/b]         Toggle detail panel
  [b]r[/b]         Reset all filters and fields
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
  [b]t[/b]         Toggle: show only selected fields
  [b]Escape[/b]    Return to main view
"""


class HelpScreen(ModalScreen):
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


class SearchInputScreen(ModalScreen):
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

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static("Text Search", id="search-title"),
            Input(placeholder="search term...", id="search-input"),
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


# --- Widgets ---

class FilterBar(Static):
    pass


class LogEntryItem(ListItem):
    def __init__(self, entry_index: int, *children: Static) -> None:
        super().__init__(*children)
        self.entry_index = entry_index


class DetailTree(Tree):
    BINDINGS = [
        Binding("j", "cursor_down", show=False),
        Binding("k", "cursor_up", show=False),
        Binding("g", "scroll_home", show=False),
        Binding("G", "scroll_end", show=False),
        Binding("ctrl+d", "page_down", show=False),
        Binding("ctrl+u", "page_up", show=False),
        Binding("s", "add_select", "Add field"),
        Binding("t", "toggle_filter_tree", "Selected only"),
    ]

    _LEADER_BINDINGS = [
        Binding("f", "noop", "Filter AND"),
        Binding("o", "noop", "Filter OR"),
        Binding("n", "noop", "Has field AND"),
        Binding("N", "noop", "Has field OR"),
        Binding("escape", "noop", "Cancel"),
    ]

    show_selected_only: bool = False
    _leader_pending: bool = False

    def action_noop(self) -> None:
        pass

    def on_key(self, event) -> None:
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
        if hasattr(self, "_saved_bindings"):
            self._bindings = self._saved_bindings
            del self._saved_bindings
        self.refresh_bindings()

    def action_toggle_filter_tree(self) -> None:
        self.show_selected_only = not self.show_selected_only
        app: JnavApp = self.app
        if app._current_detail_entry is not None:
            app._update_detail(app._current_detail_entry)

    def _do_filter(self, combine: str) -> None:
        node = self.cursor_node
        if node is None or node.data is None:
            return
        path = node.data["path"]
        value = node.data["value"]
        if isinstance(value, (dict, list)):
            return
        app: JnavApp = self.app
        expr = f'.{path} == {_jq_value_literal(value)}'
        app.add_filter(expr, combine=combine)

    def _do_presence_filter(self, combine: str) -> None:
        node = self.cursor_node
        if node is None or node.data is None:
            return
        path = node.data["path"]
        app: JnavApp = self.app
        app.add_filter(f".{path} != null", combine=combine)

    def action_add_select(self) -> None:
        node = self.cursor_node
        if node is None or node.data is None:
            return
        app: JnavApp = self.app
        app.add_column(node.data["path"])


# --- Main App ---

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
    }
    .inline-tree {
        display: none;
        padding: 0 0 0 4;
        color: $text-muted;
    }
    .expanded-mode .inline-tree {
        display: block;
    }
    #detail-tree {
        width: 40%;
        max-width: 60;
        padding: 0 0 0 2;
        display: none;
    }
    #detail-tree.visible {
        display: block;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("f", "open_filters", "Filters"),
        Binding("c", "open_columns", "Fields"),
        Binding("ctrl+f", "text_search", "Search"),
        Binding("ctrl+s", "additive_search", "Or search"),
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
    ) -> None:
        super().__init__()
        self.entries = entries
        self.all_columns: list[str] = _detect_all_columns(entries)
        self.base_columns: list[str] = _default_columns(self.all_columns)
        self.filters: list[dict] = []
        self.custom_columns: list[dict] = []
        self.visible_indices: list[int] = list(range(len(entries)))
        self._current_detail_entry: dict | None = None
        self._current_entry_index: int = 0
        self._expanded_mode: bool = False
        self._filters_paused: bool = False
        if initial_filter:
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
        self.query_one("#log-list", ListView).focus()
        self._apply_all_filters()
        self._update_filter_bar()
        if self.entries:
            self._update_detail(self.entries[0])

    # --- Filter / column management ---

    def add_filter(self, expr: str, label: str | None = None, combine: str = "and") -> None:
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
            return
        matched, error = apply_combined_filters(self.filters, self.entries)
        if error:
            self.notify(f"Filter error: {error}", severity="error", timeout=4)
            return
        self.visible_indices = matched
        self._rebuild_list()

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
        mode = "Expanded" if self._expanded_mode else "Table"
        parts.append(mode)

        if not self.filters and not self.custom_columns:
            parts.append("  f: filter  c: fields  ?: help")

        bar.update("  \u2502  ".join(parts))

    # --- Detail panel ---

    def _update_detail(self, entry: dict) -> None:
        self._current_detail_entry = entry
        tree = self.query_one("#detail-tree", DetailTree)
        tree.clear()
        sel = self._custom_columns_set()

        idx = self._current_entry_index
        ts_val = None
        for ts_key in TS_KEYS:
            ts_val = _get_nested(entry, ts_key)
            if ts_val:
                break
        label = f"#{idx + 1}"
        if ts_val:
            label += f" ({_format_timestamp(str(ts_val))})"

        if tree.show_selected_only:
            tree.root.set_label(f"{label} (selected)")
            filtered = {col: _get_nested(entry, col) for col in self.active_columns}
            _build_tree(tree.root, filtered, selected=sel)
        else:
            tree.root.set_label(label)
            _build_tree(tree.root, entry, selected=sel)
        tree.root.expand_all()

    # --- Log list ---

    def _display_cols_and_widths(self) -> tuple[list[str], list[int]]:
        display_cols = self.base_columns if self._expanded_mode else self.active_columns
        col_widths = _compute_col_widths(
            self.entries, self.visible_indices, display_cols,
        )
        return display_cols, col_widths

    def _update_header(self, display_cols: list[str], col_widths: list[int]) -> None:
        header_parts: list[str | tuple[str, str]] = []
        for col, width in zip(display_cols, col_widths):
            header_parts.append((col.ljust(width), "bold"))
            header_parts.append(" ")
        self.query_one("#log-header", Static).update(
            Text.assemble(*header_parts)
        )

    def _rebuild_list(self) -> None:
        """Full rebuild: clears and repopulates the list (use when entries change)."""
        display_cols, col_widths = self._display_cols_and_widths()
        self._update_header(display_cols, col_widths)

        lv = self.query_one("#log-list", ListView)
        custom = self._custom_columns_set()
        items: list[LogEntryItem] = []
        target_list_index = 0
        for list_idx, i in enumerate(self.visible_indices):
            entry = self.entries[i]
            summary = _entry_summary(entry, display_cols, col_widths)
            if custom:
                filtered = {col: _get_nested(entry, col) for col in custom}
                rich_tree = _build_rich_tree(filtered, custom)
            else:
                rich_tree = _build_rich_tree(entry, custom)
            items.append(LogEntryItem(
                i,
                Static(summary),
                Static(rich_tree, classes="inline-tree"),
            ))
            if i == self._current_entry_index:
                target_list_index = list_idx

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
        for item in lv.query(LogEntryItem):
            entry = self.entries[item.entry_index]
            children = list(item.query(Static))
            if len(children) >= 2:
                summary = _entry_summary(entry, display_cols, col_widths)
                children[0].update(summary)
                if custom:
                    filtered = {col: _get_nested(entry, col) for col in custom}
                    children[1].update(_build_rich_tree(filtered, custom))
                else:
                    children[1].update(_build_rich_tree(entry, custom))

    # --- Actions ---

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
            ColumnManagerScreen(self.custom_columns, self.all_columns), on_dismiss,
        )

    def action_text_search(self) -> None:
        def on_dismiss(term: str | None) -> None:
            if term:
                expr = _text_search_expr(term)
                self.add_filter(expr, label=f"search: {term}")
        self.push_screen(SearchInputScreen(), on_dismiss)

    def action_additive_search(self) -> None:
        def on_dismiss(term: str | None) -> None:
            if term:
                expr = _text_search_expr(term)
                self.add_filter(expr, label=f"search: {term}", combine="or")
        self.push_screen(SearchInputScreen(), on_dismiss)

    def action_toggle_expanded(self) -> None:
        lv = self.query_one("#log-list", ListView)
        hi = lv.index or 0

        # Compute scroll delta: sum of tree line counts for items above highlighted
        custom = self._custom_columns_set()
        delta = 0
        for list_idx, vis_idx in enumerate(self.visible_indices):
            if list_idx >= hi:
                break
            entry = self.entries[vis_idx]
            if custom:
                data = {col: _get_nested(entry, col) for col in custom}
            else:
                data = entry
            delta += _count_tree_nodes(data)

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
        self._apply_all_filters()
        self._update_filter_bar()
        if self._current_detail_entry:
            self._update_detail(self._current_detail_entry)
        self.notify("Filters and fields cleared", timeout=2)

    def action_copy_entry(self) -> None:
        if self._current_detail_entry:
            text = json.dumps(self._current_detail_entry, indent=2, default=str)
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

    @on(ListView.Highlighted, "#log-list")
    def on_log_highlighted(self, event: ListView.Highlighted) -> None:
        if event.item and isinstance(event.item, LogEntryItem):
            self._current_entry_index = event.item.entry_index
            self._update_detail(self.entries[self._current_entry_index])

    @on(ListView.Selected, "#log-list")
    def on_log_selected(self, event: ListView.Selected) -> None:
        self.action_inspect()


# --- CLI ---

def _parse_entries(lines: list[str]) -> list[dict]:
    entries = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                entries.append(obj)
        except json.JSONDecodeError:
            continue
    return entries


@click.command()
@click.argument("file", required=False, type=click.Path(exists=True))
@click.option("-f", "--filter", "initial_filter", default="", help="Initial jq filter expression")
def main(file: str | None, initial_filter: str) -> None:
    """Interactive JSON log viewer with jq filtering."""
    if file:
        with open(file) as f:
            lines = f.readlines()
    elif not sys.stdin.isatty():
        lines = sys.stdin.readlines()
        sys.stdin.close()
        sys.stdin = open("/dev/tty")
    else:
        click.echo("Usage: jnav [FILE] or pipe JSONL via stdin", err=True)
        raise SystemExit(1)

    entries = _parse_entries(lines)
    if not entries:
        click.echo("No valid JSON entries found.", err=True)
        raise SystemExit(1)

    app = JnavApp(entries=entries, initial_filter=initial_filter)
    app.title = "jnav"
    app.run()


if __name__ == "__main__":
    main()
