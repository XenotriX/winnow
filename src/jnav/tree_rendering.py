"""Shared tree rendering logic for both the interactive detail panel and inline expanded views."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

from rich.text import Text

AddBranchFn = Callable[[Text, object, str, object], None]
AddLeafFn = Callable[[Text, str, object], None]

PRIORITY_KEYS = ("timestamp", "ts", "time", "level", "severity", "message", "msg")

SELECTED_STYLE = "#61AFEF bold underline"
JSON_STRING_STYLE = "orange3 italic"
SEARCH_HIGHLIGHT_STYLE = "on dark_orange3"


def sorted_keys(d: dict[str, Any]) -> list[str]:
    priority = [k for k in PRIORITY_KEYS if k in d]
    rest = [k for k in d if k not in priority]
    return priority + rest


def value_style(value: object) -> str:
    if value is None:
        return "#ffffff dim italic"
    return "#ffffff"


def oneline(value: object) -> str:
    s = str(value)
    if "\n" in s:
        first = s[: s.index("\n")]
        return first + "\u2026"
    return s


def highlight_text(text: Text, term: str) -> Text:
    """Highlight all case-insensitive occurrences of term in a Text object."""
    if not term:
        return text
    plain = text.plain.lower()
    term_lower = term.lower()
    start = 0
    while True:
        idx = plain.find(term_lower, start)
        if idx == -1:
            break
        text.stylize(SEARCH_HIGHLIGHT_STYLE, idx, idx + len(term_lower))
        start = idx + 1
    return text


def branch_label(
    key: str,
    value: object,
    path: str,
    custom_selected: set[str],
    from_json_string: bool = False,
) -> Text:
    is_custom = path in custom_selected
    key_style = SELECTED_STYLE if is_custom else "#61AFEF italic"
    if isinstance(value, dict):
        indicator = '"{}"' if from_json_string else "{}"
        ind_style = JSON_STRING_STYLE if from_json_string else "dim"
        return Text.assemble((key, key_style), (": ", "dim"), (indicator, ind_style))
    elif isinstance(value, list):
        value = cast(list[object], value)
        n = len(value)
        indicator = f'"[{n} items]"' if from_json_string else f"[{n} items]"
        ind_style = JSON_STRING_STYLE if from_json_string else "dim"
        return Text.assemble((key, key_style), (": ", "dim"), (indicator, ind_style))
    return Text(key, style="#61AFEF italic")


def leaf_label(key: str, value: object, path: str, custom_selected: set[str]) -> Text:
    is_custom = path in custom_selected
    key_style = SELECTED_STYLE if is_custom else "#61AFEF italic"
    label = Text.assemble(
        (key, key_style), (": ", "dim"), (oneline(value), value_style(value))
    )
    label.no_wrap = True
    label.overflow = "ellipsis"
    return label


def index_label(index: int, value: object | None = None) -> Text:
    if value is None:
        return Text(f"[{index}]", style="dim")
    label = Text.assemble(
        (f"[{index}]", "dim"), (": ", "dim"), (oneline(value), value_style(value))
    )
    label.no_wrap = True
    label.overflow = "ellipsis"
    return label


def walk_tree(
    *,
    value: object,
    path: str,
    selected: set[str],
    add_branch: AddBranchFn,
    add_leaf: AddLeafFn,
    search_term: str = "",
    json_paths: set[str] | None = None,
) -> None:
    jp = json_paths or set()

    def _hl(label: Text) -> Text:
        return highlight_text(label, search_term) if search_term else label

    if isinstance(value, dict):
        value = cast(dict[str, Any], value)
        for k in sorted_keys(value):
            v = value[k]
            child_path = f"{path}.{k}" if path else k
            if isinstance(v, (dict, list)):
                v = cast(dict[str, object] | list[object], v)
                from_json = child_path in jp
                label = branch_label(
                    k, v, child_path, selected, from_json_string=from_json
                )
                add_branch(_hl(label), v, child_path, v)
            else:
                label = leaf_label(k, v, child_path, selected)
                add_leaf(_hl(label), child_path, v)
    elif isinstance(value, list):
        value = cast(list[object], value)
        for i, item in enumerate(value):
            child_path = f"{path}[{i}]"
            if isinstance(item, (dict, list)):
                item = cast(dict[str, object] | list[object], item)
                add_branch(_hl(index_label(i)), item, child_path, item)
            else:
                add_leaf(_hl(index_label(i, item)), child_path, item)
