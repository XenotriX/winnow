from dataclasses import dataclass, field

from rich.style import Style
from rich.text import Text

from jnav.json_model import ExpandedString, JsonValue
from jnav.node_path import NodePath
from jnav.tree_rendering import TreeStyle, highlight_text, oneline, render


class TestOneline:
    def test_plain_string_unchanged(self) -> None:
        assert oneline("hello") == "hello"

    def test_newline_replaced_by_ellipsis(self) -> None:
        assert oneline("first\nsecond") == "first\u2026"

    def test_only_first_line_kept(self) -> None:
        assert oneline("a\nb\nc") == "a\u2026"

    def test_leading_newline(self) -> None:
        assert oneline("\nrest") == "\u2026"

    def test_non_string_stringified(self) -> None:
        assert oneline(42) == "42"
        assert oneline(None) == "None"
        assert oneline(True) == "True"


class TestHighlightText:
    def test_no_term_returns_same_object(self) -> None:
        text = Text("hello")
        assert highlight_text(text, None, "red") is text

    def test_empty_term_returns_same_object(self) -> None:
        text = Text("hello")
        assert highlight_text(text, "", "red") is text

    def test_single_match_is_styled(self) -> None:
        text = Text("hello world")
        highlight_text(text, "world", "red")
        spans = [(s.start, s.end, str(s.style)) for s in text.spans]
        assert spans == [(6, 11, "red")]

    def test_match_is_case_insensitive(self) -> None:
        text = Text("Hello WORLD")
        highlight_text(text, "world", "red")
        spans = [(s.start, s.end) for s in text.spans]
        assert spans == [(6, 11)]

    def test_multiple_non_overlapping_matches(self) -> None:
        text = Text("ab_ab_ab")
        highlight_text(text, "ab", "red")
        spans = sorted((s.start, s.end) for s in text.spans)
        assert spans == [(0, 2), (3, 5), (6, 8)]

    def test_overlapping_matches_are_all_highlighted(self) -> None:
        text = Text("aaaa")
        highlight_text(text, "aa", "red")
        spans = {(s.start, s.end) for s in text.spans}
        assert {(0, 2), (1, 3), (2, 4)} <= spans

    def test_no_match_leaves_spans_empty(self) -> None:
        text = Text("hello")
        highlight_text(text, "xyz", "red")
        assert text.spans == []

    def test_term_longer_than_text_does_not_match(self) -> None:
        text = Text("hi")
        highlight_text(text, "hello world", "red")
        assert text.spans == []

    def test_regex_metachars_matched_literally(self) -> None:
        text = Text("a.b.c")
        highlight_text(text, ".", "red")
        spans = sorted((s.start, s.end) for s in text.spans)
        assert spans == [(1, 2), (3, 4)]


@dataclass
class _FakeNode:
    label: Text | None = None
    path: NodePath = field(default_factory=NodePath)
    value: object = None
    children: list[_FakeNode] = field(default_factory=list)


def _style() -> TreeStyle:
    return TreeStyle(
        key=Style(color="cyan"),
        value=Style(),
        null=Style(italic=True),
        json_str=Style(color="orange3", italic=True),
        search_hl=Style(bgcolor="yellow"),
    )


def _add_node(
    parent: _FakeNode,
    label: Text,
    path: NodePath,
    value: object,
) -> _FakeNode:
    node = _FakeNode(label=label, path=path, value=value)
    parent.children.append(node)
    return node


def _render_at_root(value: JsonValue, *, search_term: str | None = None) -> _FakeNode:
    root = _FakeNode()
    render(
        parent=root,
        path=NodePath() / "x",
        value=value,
        add_node=_add_node,
        style=_style(),
        search_term=search_term,
    )
    return root


class TestRenderLeaf:
    def test_scalar_becomes_leaf_with_no_children(self) -> None:
        root = _render_at_root("INFO")
        assert len(root.children) == 1
        leaf = root.children[0]
        assert leaf.children == []
        assert leaf.value == "INFO"
        assert leaf.label is not None
        assert leaf.label.plain == "x: INFO"

    def test_null_uses_null_style(self) -> None:
        root = _render_at_root(None)
        label = root.children[0].label
        assert label is not None
        spans = {(s.start, s.end, str(s.style)) for s in label.spans}
        assert any("italic" in style for (_, _, style) in spans)

    def test_multiline_value_gets_ellipsis(self) -> None:
        root = _render_at_root("first\nsecond")
        label = root.children[0].label
        assert label is not None
        assert label.plain == "x: first\u2026"


class TestRenderBranch:
    def test_dict_label_uses_brace_indicator(self) -> None:
        root = _render_at_root({"inner": 1})
        branch = root.children[0]
        assert branch.label is not None
        assert branch.label.plain == "x: {}"

    def test_list_label_shows_item_count(self) -> None:
        root = _render_at_root([1, 2, 3])
        branch = root.children[0]
        assert branch.label is not None
        assert branch.label.plain == "x: [3 items]"

    def test_empty_list_shows_zero_items(self) -> None:
        root = _render_at_root([])
        branch = root.children[0]
        assert branch.label is not None
        assert branch.label.plain == "x: [0 items]"
        assert branch.children == []

    def test_dict_children_are_rendered(self) -> None:
        root = _render_at_root({"a": 1, "b": 2})
        branch = root.children[0]
        assert [c.label.plain for c in branch.children if c.label] == [
            "a: 1",
            "b: 2",
        ]
        assert [c.path for c in branch.children] == [
            NodePath() / "x" / "a",
            NodePath() / "x" / "b",
        ]

    def test_list_items_use_index_labels(self) -> None:
        root = _render_at_root([10, 20])
        branch = root.children[0]
        assert [c.label.plain for c in branch.children if c.label] == [
            "[0]: 10",
            "[1]: 20",
        ]

    def test_nested_dict_produces_nested_tree(self) -> None:
        root = _render_at_root({"outer": {"inner": 1}})
        outer = root.children[0].children[0]
        assert outer.label is not None
        assert outer.label.plain == "outer: {}"
        inner_leaf = outer.children[0]
        assert inner_leaf.label is not None
        assert inner_leaf.label.plain == "inner: 1"
        assert inner_leaf.path == NodePath() / "x" / "outer" / "inner"


class TestRenderExpandedString:
    def test_expanded_string_shows_quoted_indicator(self) -> None:
        wrapper = ExpandedString(original='{"k":1}', parsed={"k": 1})
        root = _render_at_root(wrapper)
        branch = root.children[0]
        assert branch.label is not None
        assert branch.label.plain == 'x: "{}"'

    def test_expanded_string_recurses_into_parsed(self) -> None:
        wrapper = ExpandedString(original='{"k":1}', parsed={"k": 1})
        root = _render_at_root(wrapper)
        branch = root.children[0]
        assert len(branch.children) == 1
        leaf = branch.children[0]
        assert leaf.label is not None
        assert leaf.label.plain == "k: 1"

    def test_expanded_string_list_shows_item_count(self) -> None:
        wrapper = ExpandedString(original="[1,2]", parsed=[1, 2])
        root = _render_at_root(wrapper)
        branch = root.children[0]
        assert branch.label is not None
        assert branch.label.plain == 'x: "[2 items]"'


class TestRenderSearchHighlight:
    def test_highlight_applies_to_leaf_label(self) -> None:
        root = _render_at_root("INFO", search_term="inf")
        label = root.children[0].label
        assert label is not None
        match_start = label.plain.lower().index("inf")
        hl = [(s.start, s.end) for s in label.spans if "yellow" in str(s.style)]
        assert hl == [(match_start, match_start + len("inf"))]

    def test_highlight_applies_to_branch_label(self) -> None:
        root = _render_at_root({"inner": 1}, search_term="x")
        label = root.children[0].label
        assert label is not None
        hl = [(s.start, s.end) for s in label.spans if "yellow" in str(s.style)]
        assert hl == [(0, 1)]

    def test_no_search_term_produces_no_highlight_spans(self) -> None:
        root = _render_at_root("hello")
        label = root.children[0].label
        assert label is not None
        assert not any("yellow" in str(s.style) for s in label.spans)
