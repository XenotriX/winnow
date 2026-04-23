from dataclasses import dataclass

import orjson

from jnav.json_model import ExpandedString, JsonValue


@dataclass
class ParsedEntry:
    raw: str
    expanded: JsonValue


def parse_entry(line: str) -> ParsedEntry | None:
    """Parse a JSON line into a ``ParsedEntry`` with nested JSON-encoded
    strings expanded in place. Returns ``None`` for blank lines, invalid
    JSON, and JSON that isn't an object."""
    stripped = line.strip()
    if not stripped:
        return None
    try:
        parsed = orjson.loads(stripped)
    except orjson.JSONDecodeError, ValueError:
        return None
    expanded = expand(parsed)
    return ParsedEntry(
        raw=stripped,
        expanded=expanded,
    )


def expand(value: JsonValue) -> JsonValue:
    """Recursively expand JSON-encoded strings in a JSON value."""
    if isinstance(value, dict):
        return {k: expand(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [expand(v) for v in value]
    elif isinstance(value, str):
        try:
            parsed = orjson.loads(value)
        except orjson.JSONDecodeError, ValueError:
            return value
        return ExpandedString(original=value, parsed=expand(parsed))
    else:
        return value
