from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from rich.style import Style
from rich.text import Text

from jnav.json_model import (
    ExpandedString,
    JsonArray,
    JsonObject,
    JsonValue,
    children,
    is_container,
)
from jnav.node_path import NodePath, Segment

AddNodeFn = Callable[[Any, Text, NodePath, JsonValue], Any]


@dataclass
class TreeStyle:
    key: Style
    value: Style
    null: Style
    json_str: Style
    search_hl: Style


def oneline(value: JsonValue) -> str:
    s = str(value)
    nl = s.find("\n")
    return s if nl == -1 else s[:nl] + "\u2026"


def highlight_text(text: Text, term: str | None, style: str | Style) -> Text:
    if not term:
        return text
    plain = text.plain.lower()
    term_lower = term.lower()
    start = 0
    while (idx := plain.find(term_lower, start)) != -1:
        text.stylize(style, idx, idx + len(term_lower))
        start = idx + 1
    return text


LabelPart = tuple[str, str | Style]


def _key_prefix(seg: Segment, style: TreeStyle) -> LabelPart:
    if isinstance(seg, int):
        return (f"[{seg}]", "dim")
    return (seg, style.key)


def _container_body(
    value: JsonObject | JsonArray | ExpandedString,
    style: TreeStyle,
) -> LabelPart:
    if isinstance(value, dict):
        return "{}", "dim"
    if isinstance(value, list):
        return f"[{len(value)} items]", "dim"
    if isinstance(value.parsed, dict):
        return '"{}"', style.json_str
    assert isinstance(value.parsed, list)
    return f'"[{len(value.parsed)} items]"', style.json_str


def _key_body(
    value: JsonValue,
    style: TreeStyle,
) -> LabelPart:
    if is_container(value):
        return _container_body(value, style)
    else:
        body = oneline(value)
        body_style = style.null if value is None else style.value
        return body, body_style


def _label(
    seg: Segment,
    value: JsonValue,
    style: TreeStyle,
    term: str | None,
) -> Text:
    label = Text.assemble(
        _key_prefix(seg, style),
        (": ", "dim"),
        _key_body(value, style),
    )
    if not is_container(value):
        label.no_wrap = True
        label.overflow = "ellipsis"
    return highlight_text(label, term, style.search_hl)


def render(
    *,
    parent: Any,
    path: NodePath,
    value: JsonValue,
    add_node: AddNodeFn,
    style: TreeStyle,
    search_term: str | None = None,
) -> None:
    """Render `value` as a child of `parent`, labeled by `path[-1]`,
    then recurse into its contents. Scalars terminate naturally because
    ``children`` returns an empty iterable for them.

    :param parent: The parent node to add to. Opaque type, passed through to `add_node`.
    :param path: The path to the value being rendered. The last segment is used for labeling, and the full path is passed to `add_node`.
    :param value: The JSON value to render.
    :param add_node: A callback that adds a child to `parent` with a given label and returns the new child. Called as `add_node(parent, label, path, value)`.
    :param style: Styles to use for rendering.
    :param search_term: If given, a term to highlight in the labels.
    """
    assert len(path) > 0, "render requires a non-root path"
    seg = path[-1]
    label = _label(seg, value, style, search_term)
    node = add_node(parent, label, path, value)
    for child_seg, child_value in children(value):
        render(
            parent=node,
            path=path / child_seg,
            value=child_value,
            add_node=add_node,
            style=style,
            search_term=search_term,
        )
