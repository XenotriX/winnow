import json
import re
import jq
from collections import OrderedDict

def apply_jq_filter(
    expression: str,
    entries: list[dict],
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
    filters: list[dict],
    entries: list[dict],
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


_ASSIGNMENT_RE = re.compile(r"(?<![=!<>])=(?!=)")


def check_filter_warning(expression: str) -> str | None:
    if _ASSIGNMENT_RE.search(expression):
        return "Did you mean '==' instead of '='? ('=' is jq's update operator)"
    return None


def _is_truthy(value: object) -> bool:
    if value is None or value is False:
        return False
    if isinstance(value, (list, dict, str)) and len(value) == 0:
        return False
    return True


_PATH_SEGMENT_RE = re.compile(r"([^.\[\]]+)|\[(\d+)\]")




def get_nested(entry: dict, path: str) -> object:
    # Paths with [] (iterator) need jq
    if "[]" in path:
        jq_path = "." + path if not path.startswith(".") else path
        # Convert dotted paths to jq syntax: a.b[].c → .a.b[].c
        try:
            prog = jq.compile(f"[{jq_path}]")
            result = prog.input_value(entry).first()
            return result if result else ""
        except Exception:
            return ""
    obj = entry
    for match in _PATH_SEGMENT_RE.finditer(path):
        key, idx = match.group(1), match.group(2)
        if key is not None:
            if isinstance(obj, dict):
                obj = obj.get(key, "")
            else:
                return ""
        else:
            i = int(idx)
            if isinstance(obj, list) and i < len(obj):
                obj = obj[i]
            else:
                return ""
    return obj


def flatten_keys(obj: dict, prefix: str = "") -> list[str]:
    keys = []
    for k, v in obj.items():
        full = f"{prefix}{k}"
        if isinstance(v, dict):
            for sub_k in v:
                keys.append(f"{full}.{sub_k}")
        else:
            keys.append(full)
    return keys


def detect_all_columns(entries: list[dict]) -> list[str]:
    seen: OrderedDict[str, None] = OrderedDict()
    for entry in entries:
        for key in flatten_keys(entry):
            if key not in seen:
                seen[key] = None
    return list(seen)




def jq_value_literal(value: object) -> str:
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(value)




def _jq_path_to_str(parts: list) -> str:
    result = ""
    for p in parts:
        if isinstance(p, int):
            result += f"[{p}]"
        else:
            result = f"{result}.{p}" if result else p
    return result


def resolve_selected_paths(columns: set[str], entry: dict) -> set[str]:
    """Expand jq column expressions into concrete paths for a specific entry."""
    result: set[str] = set()
    for col in columns:
        if "[]" not in col and "|" not in col:
            result.add(col)
            continue
        jq_path = "." + col if not col.startswith(".") else col
        try:
            raw = jq.compile(f"[path({jq_path})]").input_value(entry).first()
            for parts in raw:
                result.add(_jq_path_to_str(parts))
            continue
        except Exception:
            pass
        try:
            results = jq.compile(jq_path).input_value(entry).all()
            base_expr = jq_path.split("|")[0].strip()
            raw_bases = jq.compile(f"[path({base_expr})]").input_value(entry).first()
            for base_parts in raw_bases:
                base = _jq_path_to_str(base_parts)
                for r in results:
                    if isinstance(r, dict):
                        for key in r:
                            result.add(f"{base}.{key}")
        except Exception:
            result.add(col)
    return result


