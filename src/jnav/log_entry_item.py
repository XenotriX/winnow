from __future__ import annotations

from datetime import datetime

from rich.style import Style
from rich.text import Text

from .filtering import get_nested
from .parsing import ParsedEntry
from .search_engine import SearchEngine
from .tree_rendering import highlight_text

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


def _get_level_shorthand(value: str) -> str:
    s = value[0]
    remainder = value[1:].lower()
    vowels = set("aeiouy")
    s += "".join(c for c in remainder if c not in vowels)
    s = s.upper()
    if len(s) > 3:
        s = s[:3]
    return s


def render_summary(
    parsed: ParsedEntry,
    search: SearchEngine | None = None,
    *,
    text_style: Style | None = None,
    level_styles: dict[str, Style] | None = None,
    highlight_style: Style | None = None,
) -> Text:
    _ts = text_style or Style()
    _hl = highlight_style or Style()
    parts: list[str | tuple[str, str | Style]] = [" "]

    ts_val = get_nested(parsed.expanded, "ts")
    ts_str = str(ts_val) if ts_val else ""
    if ts_str:
        try:
            dt = datetime.fromisoformat(ts_str)
            ts_str = dt.strftime("%H:%M:%S") + f".{dt.microsecond // 1000:03d}"
        except ValueError, TypeError:
            pass
        parts.append((ts_str, _ts))
        parts.append(" ")

    level_val = get_nested(parsed.expanded, "level")
    level_str = str(level_val) if level_val else ""
    if level_str:
        component = LEVEL_COMPONENTS.get(level_str.strip().lower())
        short = _get_level_shorthand(level_str)
        if component and level_styles and component in level_styles:
            parts.append((short, level_styles[component]))
        else:
            parts.append((short, _ts))
        parts.append(" ")

    msg_val = get_nested(parsed.expanded, "message")
    msg_str = str(msg_val) if msg_val or msg_val == 0 else ""
    parts.append((msg_str, _ts))

    text = Text.assemble(*parts)
    text.no_wrap = True
    text.overflow = "ellipsis"
    search_term = search.term if search else None
    return highlight_text(text, search_term, _hl)
