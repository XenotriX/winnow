from __future__ import annotations

from collections.abc import Callable
from typing import Any, Generic, Protocol, TypeVar, cast

from rich.style import Style
from rich.text import Text

T = TypeVar("T")

PRIORITY_KEYS = ("timestamp", "ts", "time", "level", "severity", "message", "msg")

DEFAULT_JSON_STRING_STYLE = "orange3 italic"
DEFAULT_SEARCH_HIGHLIGHT_STYLE = "on dark_orange3"
DEFAULT_VALUE_STYLE = ""
DEFAULT_VALUE_NULL_STYLE = "dim italic"

AddBranchFn = Callable[[Any, Text, str, object], Any]
AddLeafFn = Callable[[Any, Text, str, object], None]


class TreeVisitor(Protocol):
    def enter_property(self, key: str, value: dict[str, Any] | list[object], path: str, from_json: bool) -> None: ...
    def exit_property(self) -> None: ...
    def on_property(self, key: str, value: object, path: str) -> None: ...
    def enter_item(self, index: int, value: dict[str, Any] | list[object], path: str) -> None: ...
    def exit_item(self) -> None: ...
    def on_item(self, index: int, value: object, path: str) -> None: ...


def sorted_keys(d: dict[str, Any]) -> list[str]:
    priority = [k for k in PRIORITY_KEYS if k in d]
    rest = [k for k in d if k not in priority]
    return priority + rest


def oneline(value: object) -> str:
    s = str(value)
    if "\n" in s:
        first = s[: s.index("\n")]
        return first + "\u2026"
    return s


def highlight_text(
    text: Text,
    term: str,
    style: str | Style = DEFAULT_SEARCH_HIGHLIGHT_STYLE,
) -> Text:
    if not term:
        return text
    plain = text.plain.lower()
    term_lower = term.lower()
    start = 0
    while True:
        idx = plain.find(term_lower, start)
        if idx == -1:
            break
        text.stylize(style, idx, idx + len(term_lower))
        start = idx + 1
    return text


class TreeBuildVisitor(Generic[T]):
    def __init__(
        self,
        *,
        root: T,
        add_branch: AddBranchFn,
        add_leaf: AddLeafFn,
        selected: set[str],
        key_style: str | Style,
        selected_style: str | Style,
        value_style: str | Style = DEFAULT_VALUE_STYLE,
        value_null_style: str | Style = DEFAULT_VALUE_NULL_STYLE,
        json_string_style: str | Style = DEFAULT_JSON_STRING_STYLE,
        search_highlight_style: str | Style = DEFAULT_SEARCH_HIGHLIGHT_STYLE,
        search_term: str = "",
    ) -> None:
        self._stack: list[T] = [root]
        self._add_branch = add_branch
        self._add_leaf = add_leaf
        self._selected = selected
        self._key_style = key_style
        self._selected_style = selected_style
        self._value_style = value_style
        self._value_null_style = value_null_style
        self._json_string_style = json_string_style
        self._search_highlight_style = search_highlight_style
        self._search_term = search_term

    def _style_for(self, path: str) -> str | Style:
        return self._selected_style if path in self._selected else self._key_style

    def _val_style(self, value: object) -> str | Style:
        return self._value_null_style if value is None else self._value_style

    def _hl(self, text: Text) -> Text:
        return highlight_text(text, self._search_term, self._search_highlight_style) if self._search_term else text

    def enter_property(self, key: str, value: dict[str, Any] | list[object], path: str, from_json: bool) -> None:
        style = self._style_for(path)
        if isinstance(value, dict):
            indicator = '"{}"' if from_json else "{}"
        else:
            n = len(value)
            indicator = f'"[{n} items]"' if from_json else f"[{n} items]"
        ind_style = self._json_string_style if from_json else "dim"
        label = self._hl(Text.assemble((key, style), (": ", "dim"), (indicator, ind_style)))
        new_node = self._add_branch(self._stack[-1], label, path, value)
        self._stack.append(new_node)

    def exit_property(self) -> None:
        self._stack.pop()

    def on_property(self, key: str, value: object, path: str) -> None:
        style = self._style_for(path)
        label = self._hl(Text.assemble(
            (key, style), (": ", "dim"), (oneline(value), self._val_style(value))
        ))
        label.no_wrap = True
        label.overflow = "ellipsis"
        self._add_leaf(self._stack[-1], label, path, value)

    def enter_item(self, index: int, value: dict[str, Any] | list[object], path: str) -> None:
        label = self._hl(Text(f"[{index}]", style="dim"))
        new_node = self._add_branch(self._stack[-1], label, path, value)
        self._stack.append(new_node)

    def exit_item(self) -> None:
        self._stack.pop()

    def on_item(self, index: int, value: object, path: str) -> None:
        label = self._hl(Text.assemble(
            (f"[{index}]", "dim"), (": ", "dim"), (oneline(value), self._val_style(value))
        ))
        label.no_wrap = True
        label.overflow = "ellipsis"
        self._add_leaf(self._stack[-1], label, path, value)


def walk_tree(
    *,
    value: object,
    path: str,
    visitor: TreeVisitor,
    json_paths: set[str] | None = None,
) -> None:
    jp = json_paths or set()

    if isinstance(value, dict):
        value = cast(dict[str, Any], value)
        for k in sorted_keys(value):
            v = value[k]
            child_path = f"{path}.{k}" if path else k
            if isinstance(v, (dict, list)):
                v = cast(dict[str, Any] | list[object], v)
                from_json = child_path in jp
                visitor.enter_property(k, v, child_path, from_json)
                walk_tree(value=v, path=child_path, visitor=visitor, json_paths=json_paths)
                visitor.exit_property()
            else:
                visitor.on_property(k, v, child_path)
    elif isinstance(value, list):
        value = cast(list[object], value)
        for i, item in enumerate(value):
            child_path = f"{path}[{i}]"
            if isinstance(item, (dict, list)):
                item = cast(dict[str, Any] | list[object], item)
                visitor.enter_item(i, item, child_path)
                walk_tree(value=item, path=child_path, visitor=visitor, json_paths=json_paths)
                visitor.exit_item()
            else:
                visitor.on_item(i, item, child_path)
