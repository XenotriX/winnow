from rich.text import Text
from rich.tree import Tree as RichTree

from jnav.selector_provider import Selector

from .json_model import JsonValue
from .node_path import NodePath
from .parsing import ParsedEntry
from .search_engine import SearchEngine
from .tree_rendering import TreeStyle, render


def _add_node(
    parent: RichTree,
    label: Text,
    path: NodePath,
    value: JsonValue,
) -> RichTree:
    del path, value  # unused
    return parent.add(label)


def render_inline_tree(
    parsed: ParsedEntry,
    *,
    custom_fields: list[Selector],
    style: TreeStyle,
    search: SearchEngine | None = None,
) -> RichTree | None:
    if not custom_fields:
        return None
    entries = [(s, s.resolve(parsed.expanded)) for s in custom_fields]
    filtered = [(s, v) for s, v in entries if v is not None]
    if not filtered:
        return None

    tree = RichTree("", guide_style="dim", hide_root=True)
    search_term = search.term if search else None
    for sel, value in filtered:
        render(
            parent=tree,
            path=NodePath() / sel.path,
            value=value,
            add_node=_add_node,
            style=style,
            search_term=search_term,
        )
    return tree
