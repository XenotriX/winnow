from __future__ import annotations

from dataclasses import dataclass

from rich.console import Group, RenderableType
from rich.padding import Padding
from rich.style import Style
from textual.color import Color

from .field_manager import FieldManager
from .inline_tree import render_inline_tree
from .log_entry_item import render_summary
from .search_engine import SearchEngine
from .store import IndexedEntry


@dataclass(frozen=True)
class EntryStyles:
    text: Style
    levels: dict[str, Style]
    highlight: Style
    cursor_bg: Style
    tree_key: Style
    tree_key_selected: Style
    tree_value: Style
    tree_value_null: Style
    tree_json_string: Style
    tree_search_highlight: Style
    tree_bg: Color
    cursor_color: Color


class LogEntryRenderer:
    def __init__(
        self,
        *,
        search: SearchEngine,
        fields: FieldManager,
    ) -> None:
        self._search = search
        self._fields = fields

    def render(
        self,
        ie: IndexedEntry,
        *,
        styles: EntryStyles,
        is_cursor: bool,
        expanded: bool,
        width: int,
    ) -> RenderableType:
        text = render_summary(
            ie.entry,
            self._fields.mapping,
            self._search,
            text_style=styles.text,
            level_styles=styles.levels,
            highlight_style=styles.highlight,
        )
        text.truncate(width - 2, overflow="ellipsis", pad=False)

        if is_cursor:
            text.stylize(styles.cursor_bg)
            text.pad_right(width - text.cell_len)
            text.style = styles.cursor_bg

        if not expanded:
            return text

        tree = render_inline_tree(
            ie.entry,
            custom_fields=self._fields.active_fields,
            search=self._search,
            key_style=styles.tree_key,
            selected_style=styles.tree_key_selected,
            value_style=styles.tree_value,
            value_null_style=styles.tree_value_null,
            json_string_style=styles.tree_json_string,
            search_highlight_style=styles.tree_search_highlight,
        )
        if tree is None:
            return text

        tree_bg = styles.tree_bg
        if is_cursor:
            tree_bg = tree_bg.blend(styles.cursor_color, styles.cursor_color.a * 0.66)
        tree_style = Style(bgcolor=tree_bg.rich_color)
        padded_tree = Padding(tree, (0, 2, 0, 5), style=tree_style, expand=True)
        return Group(text, padded_tree)
