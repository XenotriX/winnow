from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from rich.style import Style
from rich.text import Text
from textual.widgets import Static

from .filtering import get_nested
from .parsing import ParsedEntry
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
    COMPONENT_CLASSES = {
        "summary--level-error",
        "summary--level-warning",
        "summary--level-info",
        "summary--level-debug",
        "summary--text",
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

    def __init__(self) -> None:
        super().__init__()
        self._parsed: ParsedEntry | None = None
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

    def set_entry(self, parsed: ParsedEntry) -> None:
        self._parsed = parsed

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

    def refresh_content(
        self,
        search: str,
    ) -> None:
        if self._parsed is None:
            return

        parts: list[str | tuple[str, str | Style]] = []
        for col in self.columns:
            val = get_nested(self._parsed.expanded, col.key)
            s = str(val) if val or val == 0 else ""
            formatted = col.format(s)
            parts.append(formatted)
            parts.append(" ")
        text = Text.assemble(*parts) if parts else Text("(empty)")
        self.update(highlight_text(text, search))
