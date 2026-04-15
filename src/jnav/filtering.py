import functools
import json
import math
import re
from collections.abc import Sequence
from typing import Annotated, Any, Literal, cast

import jq
from pydantic import BaseModel, Discriminator, Field


class Filter(BaseModel):
    type: Literal["leaf"] = "leaf"
    expr: str
    enabled: bool = True
    negated: bool = False
    label: str | None = None


class FilterGroup(BaseModel):
    type: Literal["group"] = "group"
    operator: Literal["and", "or"] = "and"
    enabled: bool = True
    negated: bool = False
    label: str | None = None
    collapsed: bool = False
    children: list[FilterNode] = Field(default_factory=list)


FilterNode = Annotated[Filter | FilterGroup, Discriminator("type")]

FilterGroup.model_rebuild()


@functools.lru_cache(maxsize=32)
def _compile_jq(expression: str):
    return jq.compile(expression)


def apply_jq_filter(
    expression: str,
    entries: list[dict[str, Any]],
) -> tuple[list[int], str | None]:
    try:
        prog = _compile_jq(expression)
    except ValueError as e:
        return [], str(e)
    matched: list[int] = []
    for i, entry in enumerate(entries):
        try:
            results = prog.input_value(entry).all()
            if any(r is not None and r is not False for r in results):
                matched.append(i)
        except ValueError:
            continue
    return matched, None


def build_expression(node: FilterNode) -> str | None:
    """Recursively build a jq expression from a filter tree.

    Returns None if the node is disabled or has no effective children.
    """
    if not node.enabled:
        return None

    if isinstance(node, Filter):
        expr = node.expr
        if node.negated:
            expr = f"{expr} | not"
        return expr

    child_exprs: list[tuple[str, FilterNode]] = []
    for child in node.children:
        child_expr = build_expression(child)
        if child_expr is not None:
            child_exprs.append((child_expr, child))

    if not child_exprs:
        return None

    if len(child_exprs) == 1:
        result = child_exprs[0][0]
    else:
        joiner = f" {node.operator} "
        wrapped: list[str] = []
        for expr, child in child_exprs:
            needs_parens = "|" in expr or (
                isinstance(child, FilterGroup)
                and len(child.children) > 1
                and child.operator != node.operator
            )
            wrapped.append(f"({expr})" if needs_parens else expr)
        result = joiner.join(wrapped)

    if node.negated:
        result = f"({result}) | not"

    return result


def apply_filter_tree(
    root: FilterGroup,
    entries: list[dict[str, Any]],
) -> tuple[list[int], str | None]:
    """Apply a filter tree to a list of entries."""
    combined = build_expression(root)
    if combined is None:
        return list(range(len(entries))), None
    return apply_jq_filter(combined, entries)


def text_search_expr(term: str) -> str:
    escaped = term.lower().replace("\\", "\\\\").replace('"', '\\"')
    return f'[.. | strings] | any(ascii_downcase | contains("{escaped}"))'


_ASSIGNMENT_RE = re.compile(r"(?<![=!<>])=(?!=)")
_STRING_LITERAL_RE = re.compile(r'"[^"\\]*(?:\\.[^"\\]*)*"')


def check_filter_warning(expression: str) -> str | None:
    without_strings = _STRING_LITERAL_RE.sub('""', expression)
    if _ASSIGNMENT_RE.search(without_strings):
        return "jq update operators don't filter — did you mean a comparison like '=='?"
    return None


def get_nested(entry: dict[str, Any], path: str) -> object:
    try:
        results = _compile_jq(path).input_value(entry).all()
    except ValueError:
        return None
    if len(results) == 1:
        return results[0]
    return results


def jq_value_literal(value: object) -> str:
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        if not math.isfinite(value):
            raise ValueError(f"jq does not support {value!r}")
        return str(value)
    return json.dumps(value)


def _jq_path_to_str(parts: Sequence[str | int]) -> str:
    result = ""
    for p in parts:
        if isinstance(p, int):
            result += f"[{p}]"
        else:
            result = f"{result}.{p}" if result else p
    return result


def resolve_selected_paths(columns: set[str], entry: dict[str, Any]) -> set[str]:
    """Expand jq column expressions into concrete paths for a specific entry."""
    result: set[str] = set()
    for col in columns:
        if "[]" not in col and "|" not in col:
            result.add(col.lstrip("."))
            continue
        jq_path = col
        try:
            raw = jq.compile(f"[path({jq_path})]").input_value(entry).first()
            for parts in raw:
                result.add(_jq_path_to_str(parts))
            continue
        except ValueError:
            pass
        try:
            results = jq.compile(jq_path).input_value(entry).all()
            base_expr = jq_path.split("|")[0].strip()
            raw_bases = jq.compile(f"[path({base_expr})]").input_value(entry).first()
            for base_parts in raw_bases:
                base = _jq_path_to_str(base_parts)
                for r in results:
                    if isinstance(r, dict):
                        r = cast(dict[str, object], r)
                        for key in r:
                            result.add(f"{base}.{key}")
        except ValueError:
            result.add(col)
    return result
