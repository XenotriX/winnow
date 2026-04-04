import json
from dataclasses import dataclass, field
from typing import Any, cast


@dataclass
class ParsedEntry:
    raw: dict[str, Any]
    expanded: dict[str, Any]
    expanded_paths: set[str] = field(default_factory=set)


def parse_line(line: str) -> dict[str, Any] | None:
    """Parse a single line into a JSON object, or return None if invalid."""
    line = line.strip()
    if not line:
        return None
    try:
        obj = json.loads(line)
        if isinstance(obj, dict):
            return cast(dict[str, Any], obj)
        return None
    except json.JSONDecodeError:
        return None


def expand_json_strings(
    obj: object,
    path: str = "",
    expanded_paths: set[str] | None = None,
) -> object:
    """Recursively expand JSON-encoded strings, tracking which paths were strings."""
    if expanded_paths is None:
        expanded_paths = set()

    # Recurse into dicts
    if isinstance(obj, dict):
        obj = cast(dict[str, Any], obj)
        return {
            k: expand_json_strings(v, f"{path}.{k}" if path else k, expanded_paths)
            for k, v in obj.items()
        }

    # Recurse into lists
    if isinstance(obj, list):
        obj = cast(list[Any], obj)
        return [
            expand_json_strings(item, f"{path}[{i}]", expanded_paths)
            for i, item in enumerate(obj)
        ]

    # Try to parse JSON strings
    if isinstance(obj, str) and obj and obj[0] in ("{", "["):
        try:
            parsed = json.loads(obj)
            if isinstance(parsed, (dict, list)):
                parsed = cast(dict[str, Any] | list[Any], parsed)
                expanded_paths.add(path)
                return expand_json_strings(parsed, path, expanded_paths)
        except json.JSONDecodeError, ValueError:
            pass
    return obj


def preprocess_entry(entry: dict[str, Any]) -> ParsedEntry:
    """Parse and expand a raw JSON dict into a ParsedEntry."""
    expanded_paths: set[str] = set()
    expanded = expand_json_strings(entry, "", expanded_paths)
    assert isinstance(expanded, dict)
    return ParsedEntry(
        raw=entry,
        expanded=cast(dict[str, Any], expanded),
        expanded_paths=expanded_paths,
    )
