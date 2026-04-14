from datetime import datetime, timezone

from rich.style import Style
from rich.text import Text

from .field_mapping import FieldMapping, TimestampFormat
from .parsing import ParsedEntry
from .search_engine import SearchEngine
from .tree_rendering import highlight_text

LEVEL_COMPONENTS = {
    "error": "summary--level-error",
    "fatal": "summary--level-fatal",
    "critical": "summary--level-critical",
    "warn": "summary--level-warning",
    "warning": "summary--level-warning",
    "info": "summary--level-info",
    "debug": "summary--level-debug",
    "trace": "summary--level-trace",
}

_EPOCH_DIVISORS: dict[TimestampFormat, int] = {
    "epoch_s": 1,
    "epoch_ms": 1_000,
    "epoch_us": 1_000_000,
    "epoch_ns": 1_000_000_000,
}


def format_timestamp(value: object, fmt: TimestampFormat) -> str:
    """Format a timestamp value as HH:MM:SS.mmm. Falls back to the raw string
    representation on any parsing failure."""
    try:
        if fmt == "iso8601":
            dt = datetime.fromisoformat(str(value))
        else:
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                return str(value)
            dt = datetime.fromtimestamp(
                float(value) / _EPOCH_DIVISORS[fmt], tz=timezone.utc
            )
        return dt.strftime("%H:%M:%S") + f".{dt.microsecond // 1000:03d}"
    except ValueError, TypeError, OSError, OverflowError:
        return str(value)


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
    mapping: FieldMapping,
    search: SearchEngine | None = None,
    *,
    text_style: Style | None = None,
    level_styles: dict[str, Style] | None = None,
    highlight_style: Style | None = None,
) -> Text:
    _ts = text_style or Style()
    _hl = highlight_style or Style()
    parts: list[str | tuple[str, str | Style]] = [" "]

    if mapping.timestamp is not None:
        ts_val = parsed.expanded.get(mapping.timestamp.path)
        if ts_val not in (None, ""):
            parts.append((format_timestamp(ts_val, mapping.timestamp.format), _ts))
            parts.append(" ")

    if mapping.level is not None:
        level_val = parsed.expanded.get(mapping.level)
        level_str = str(level_val) if level_val else ""
        if level_str:
            component = LEVEL_COMPONENTS.get(level_str.strip().lower())
            short = _get_level_shorthand(level_str)
            if component and level_styles and component in level_styles:
                parts.append((short, level_styles[component]))
            else:
                parts.append((short, _ts))
            parts.append(" ")

    if mapping.message is not None:
        msg_val = parsed.expanded.get(mapping.message)
        msg_str = str(msg_val) if msg_val or msg_val == 0 else ""
        parts.append((msg_str, _ts))

    text = Text.assemble(*parts)
    text.no_wrap = True
    text.overflow = "ellipsis"
    search_term = search.term if search else None
    return highlight_text(text, search_term, _hl)
