"""Shared tree rendering logic for both the interactive detail panel and inline expanded views."""

from __future__ import annotations
from typing import TypedDict

from rich.text import Text
from rich.tree import Tree as RichTree
from textual.widgets.tree import TreeNode

PRIORITY_KEYS = ("timestamp", "ts", "time", "level", "severity", "message", "msg")

SELECTED_STYLE = "bold bright_green underline"
JSON_STRING_STYLE = "orange3 italic"
SEARCH_HIGHLIGHT_STYLE = "on dark_orange3"


def sorted_keys(d: dict) -> list[str]:
    priority = [k for k in PRIORITY_KEYS if k in d]
    rest = [k for k in d if k not in priority]
    return priority + rest


def value_style(value: object) -> str:
    if isinstance(value, bool):
        return "bright_magenta"
    if value is None:
        return "dim italic"
    if isinstance(value, (int, float)):
        return "bright_cyan"
    if isinstance(value, str):
        return "orange3"
    return ""


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
    key_style = SELECTED_STYLE if is_custom else "bold"
    if isinstance(value, dict):
        indicator = '"{}"' if from_json_string else "{}"
        ind_style = JSON_STRING_STYLE if from_json_string else "dim"
        return Text.assemble((key, key_style), (": ", "dim"), (indicator, ind_style))
    elif isinstance(value, list):
        n = len(value)
        indicator = f'"[{n} items]"' if from_json_string else f"[{n} items]"
        ind_style = JSON_STRING_STYLE if from_json_string else "dim"
        return Text.assemble((key, key_style), (": ", "dim"), (indicator, ind_style))
    return Text(key, style="bold")


def leaf_label(key: str, value: object, path: str, custom_selected: set[str]) -> Text:
    is_custom = path in custom_selected
    key_style = SELECTED_STYLE if is_custom else "bold"
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
    value: object,
    path: str,
    selected: set[str],
    add_branch,
    add_leaf,
    search_term: str = "",
    json_paths: set[str] | None = None,
) -> None:
    """Shared tree traversal. Calls add_branch(label, children_value, path, value)
    and add_leaf(label, path, value) for each node."""
    jp = json_paths or set()

    def _hl(label: Text) -> Text:
        return highlight_text(label, search_term) if search_term else label

    if isinstance(value, dict):
        for k in sorted_keys(value):
            v = value[k]
            child_path = f"{path}.{k}" if path else k
            if isinstance(v, (dict, list)):
                from_json = child_path in jp
                label = branch_label(
                    k, v, child_path, selected, from_json_string=from_json
                )
                add_branch(_hl(label), v, child_path, v)
            else:
                label = leaf_label(k, v, child_path, selected)
                add_leaf(_hl(label), child_path, v)
    elif isinstance(value, list):
        for i, item in enumerate(value):
            child_path = f"{path}[{i}]"
            if isinstance(item, (dict, list)):
                add_branch(_hl(index_label(i)), item, child_path, item)
            else:
                add_leaf(_hl(index_label(i, item)), child_path, item)


# --- Interactive tree (detail panel) ---

class TreeNodeData(TypedDict):
    path: str
    value: object


def build_tree(
    node: TreeNode[TreeNodeData],
    value: object,
    path: str = "",
    selected: set[str] | None = None,
    search_term: str = "",
    json_paths: set[str] | None = None,
) -> None:
    sel = selected or set()

    def add_branch(label, children_value, child_path, orig_value):
        branch = node.add(label, data={"path": child_path, "value": orig_value})
        build_tree(branch, children_value, child_path, sel, search_term, json_paths)

    def add_leaf(label, child_path, orig_value):
        node.add_leaf(label, data={"path": child_path, "value": orig_value})

    walk_tree(value, path, sel, add_branch, add_leaf, search_term, json_paths)


def count_tree_nodes(value: object) -> int:
    """Count nodes for scroll offset calculation."""
    count = 0

    def add_branch(label, children_value, child_path, orig_value):
        nonlocal count
        count += 1 + count_tree_nodes(children_value)

    def add_leaf(label, child_path, orig_value):
        nonlocal count
        count += 1

    walk_tree(value, "", set(), add_branch, add_leaf)
    return count


# --- Static tree (inline expanded view) ---


def build_rich_tree(
    entry: dict,
    custom_selected: set[str],
    search_term: str = "",
    json_paths: set[str] | None = None,
) -> RichTree:
    tree = RichTree("", guide_style="dim", hide_root=True)
    _populate_rich_tree(tree, entry, "", custom_selected, search_term, json_paths)
    return tree


def _populate_rich_tree(
    node: RichTree,
    value: object,
    path: str,
    custom_selected: set[str],
    search_term: str = "",
    json_paths: set[str] | None = None,
) -> None:
    def add_branch(label, children_value, child_path, orig_value):
        branch = node.add(label)
        _populate_rich_tree(
            branch, children_value, child_path, custom_selected, search_term, json_paths
        )

    def add_leaf(label, child_path, orig_value):
        node.add(label)

    walk_tree(
        value, path, custom_selected, add_branch, add_leaf, search_term, json_paths
    )
