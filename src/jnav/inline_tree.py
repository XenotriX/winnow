from __future__ import annotations

from rich.style import Style
from rich.text import Text
from rich.tree import Tree as RichTree

from .filtering import get_nested
from .parsing import ParsedEntry
from .search_engine import SearchEngine
from .tree_rendering import TreeBuildVisitor, walk_tree


def _add_branch(
    parent: RichTree,
    label: Text,
    path: str,
    value: object,
) -> RichTree:
    del path, value  # unused
    return parent.add(label)


def _add_leaf(
    parent: RichTree,
    label: Text,
    path: str,
    value: object,
) -> None:
    del path, value  # unused
    parent.add(label)


def render_inline_tree(
    parsed: ParsedEntry,
    *,
    custom_fields: set[str],
    search: SearchEngine | None = None,
    key_style: Style | None = None,
    selected_style: Style | None = None,
    value_style: Style | None = None,
    value_null_style: Style | None = None,
    json_string_style: Style | None = None,
    search_highlight_style: Style | None = None,
) -> RichTree | None:
    if not custom_fields:
        return None
    _default = Style()
    filtered = {f: get_nested(parsed.expanded, f) for f in custom_fields}
    tree = RichTree("", guide_style="dim", hide_root=True)
    visitor = TreeBuildVisitor(
        root=tree,
        add_branch=_add_branch,
        add_leaf=_add_leaf,
        selected=custom_fields,
        key_style=key_style or _default,
        selected_style=selected_style or _default,
        value_style=value_style or _default,
        value_null_style=value_null_style or _default,
        json_string_style=json_string_style or _default,
        search_highlight_style=search_highlight_style or _default,
        search_term=search.term if search else None,
    )
    walk_tree(
        value=filtered,
        path="",
        visitor=visitor,
        json_paths=parsed.expanded_paths,
    )
    return tree
