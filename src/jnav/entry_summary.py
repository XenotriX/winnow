from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Callable

logger = logging.getLogger(__name__)

from rich.style import Style
from rich.text import Text
from textual.widgets import Static

if TYPE_CHECKING:
    from textual import getters
    from textual.app import App

from .filtering import get_nested
from .parsing import ParsedEntry
from .search_engine import SearchEngine
from .tree_rendering import highlight_text

MAX_CELL_WIDTH = 50

TS_KEYS = {"timestamp", "ts", "time"}

LEVEL_COMPONENTS = {
    "error": "summary--level-error",
    "fatal": "summary--level-error",
    "critical": "summary--level-error",
    "warn": "summary--level-warning",
    "warning": "summary--level-warning",
    "info": "summary--level-info",
    "debug": "summary--level-debug",
    "trace": "summary--level-debug",
}

def get_level_shorthand(value: str) -> str:
    s = value[0]
    remainder = value[1:].lower()

    # remove vowels
    vowels = list("aeiouy")
    s += "".join(list(filter(lambda x: x not in vowels, list(remainder))))
    s = s.upper()
    if len(s) > 3:
        s = s[:3]
    return s


def truncate(value: object, width: int = MAX_CELL_WIDTH) -> str:
    s = str(value) if not isinstance(value, str) else value
    if len(s) > width:
        return s[: width - 1] + "\u2026"
    return s


display_cols = ["ts", "level", "message"]
col_widths = [12, 5, 20]


@dataclass
class Column:
    key: str
    format: Callable[[str], tuple[str, Style]]


class EntrySummary(Static):
    if TYPE_CHECKING:
        app = getters.app(App[None])

    COMPONENT_CLASSES = {
        "summary--level-error",
        "summary--level-warning",
        "summary--level-info",
        "summary--level-debug",
        "summary--text",
        "summary--search-highlight",
    }

    DEFAULT_CSS = """
    EntrySummary {
        height: 1;
        overflow: hidden;
        & > .summary--level-error { color: $error; text-style: bold; }
        & > .summary--level-warning { color: $warning; text-style: bold; }
        & > .summary--level-info { color: $primary; text-style: bold; }
        & > .summary--level-debug { color: $success; text-style: bold; }
        & > .summary--text { color: $foreground; }
    }
    """

    def __init__(self, parsed: ParsedEntry, search: SearchEngine) -> None:
        super().__init__()
        self._parsed = parsed
        self._search = search
        self.columns: list[Column] = [
            Column(
                key="ts",
                format=self.format_timestamp,
            ),
            Column(
                key="level",
                format=self.format_level,
            ),
            Column(
                key="message",
                format=self.format_default,
            ),
        ]

    async def on_mount(self) -> None:
        await self._search.on_change.subscribe_async(self._on_change)
        self.app.theme_changed_signal.subscribe(self, lambda _: self._render_summary())
        self.call_after_refresh(self._render_summary)

    def format_default(self, value: str) -> tuple[str, Style]:
        text_style = self.get_component_rich_style("summary--text", partial=True)
        return (value, text_style)

    def format_timestamp(self, value: str) -> tuple[str, Style]:
        text_style = self.get_component_rich_style("summary--text", partial=True)
        try:
            dt = datetime.fromisoformat(value)
            s = dt.strftime("%H:%M:%S") + f".{dt.microsecond // 1000:03d}"
            return (s, text_style)
        except ValueError, TypeError:
            return self.format_default(value)

    def format_level(self, s: str) -> tuple[str, Style]:
        component = LEVEL_COMPONENTS.get(s.strip().lower())
        s = get_level_shorthand(s)
        if component:
            level_style = self.get_component_rich_style(component, partial=True)
            return (s, level_style)
        else:
            return self.format_default(s)

    async def _on_change(self, _: None) -> None:
        self._render_summary()

    def _render_summary(self) -> None:
        if not self.is_mounted:
            logger.warning("_render_summary called before mount")
            return
        parts: list[str | tuple[str, str | Style]] = []
        for col in self.columns:
            val = get_nested(self._parsed.expanded, col.key)
            s = str(val) if val or val == 0 else ""
            formatted = col.format(s)
            parts.append(formatted)
            parts.append(" ")
        text = Text.assemble(*parts) if parts else Text("(empty)")
        hl_style = self.get_component_rich_style("summary--search-highlight", partial=True)
        self.update(highlight_text(text, self._search.term, hl_style))
