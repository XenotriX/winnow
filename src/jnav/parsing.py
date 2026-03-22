import json
from typing import Any

def parse_entries(lines: list[str]) -> list[Any]:
    """Parse lines into JSON objects"""
    entries: list[Any] = []
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


def expand_json_strings(
    obj: object, path: str = "", json_paths: set[str] | None = None
) -> object:
    """Recursively expand JSON-encoded strings, tracking which paths were strings."""
    if json_paths is None:
        json_paths = set()
    if isinstance(obj, dict):
        return {
            k: expand_json_strings(v, f"{path}.{k}" if path else k, json_paths)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [
            expand_json_strings(item, f"{path}[{i}]", json_paths)
            for i, item in enumerate(obj)
        ]
    if isinstance(obj, str) and obj and obj[0] in ("{", "["):
        try:
            parsed = json.loads(obj)
            if isinstance(parsed, (dict, list)):
                json_paths.add(path)
                return expand_json_strings(parsed, path, json_paths)
        except json.JSONDecodeError, ValueError:
            pass
    return obj


def preprocess_entry(entry: dict) -> tuple[dict, set[str]]:
    json_paths: set[str] = set()
    expanded = expand_json_strings(entry, "", json_paths)
    return expanded, json_paths
