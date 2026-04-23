import functools
import json
import math
import re
from typing import Annotated, Literal

import jq
from pydantic import BaseModel, Discriminator, Field

from jnav.json_model import JsonValue


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
    entries: list[JsonValue],
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
    entries: list[JsonValue],
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
        return "jq update operators don't filter. Did you mean a comparison like '=='?"
    return None


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
