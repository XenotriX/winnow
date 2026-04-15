import json
from typing import Any

import jq
import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from jnav.filtering import (
    Filter,
    FilterGroup,
    _compile_jq,  # pyright: ignore[reportPrivateUsage]
    _jq_path_to_str,  # pyright: ignore[reportPrivateUsage]
    apply_filter_tree,
    apply_jq_filter,
    build_expression,
    check_filter_warning,
    get_nested,
    jq_value_literal,
    resolve_selected_paths,
    text_search_expr,
)


@pytest.fixture(autouse=True)
def _clear_jq_cache() -> None:  # pyright: ignore[reportUnusedFunction]
    _compile_jq.cache_clear()


class TestCompileJq:
    def test_returns_identical_program_on_cache_hit(self) -> None:
        a = _compile_jq(".foo")
        b = _compile_jq(".foo")
        assert a is b

    def test_invalid_expression_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            _compile_jq("this is not jq !!!")

    def test_eviction_after_cache_full(self) -> None:
        first = _compile_jq(".f0")
        for i in range(1, 40):
            _compile_jq(f".f{i}")
        assert _compile_jq.cache_info().currsize == 32
        assert _compile_jq(".f0") is not first


class TestApplyJqFilter:
    def test_filter_matches_subset_of_entries(self) -> None:
        entries = [
            {"level": "INFO"},
            {"level": "ERROR"},
            {"level": "INFO"},
        ]
        indices, error = apply_jq_filter('.level == "ERROR"', entries)
        assert indices == [1]
        assert error is None

    def test_invalid_expression_returns_empty_with_error(self) -> None:
        indices, error = apply_jq_filter("this is not jq !!!", [{"a": 1}])
        assert indices == []
        assert error is not None

    def test_empty_entries_returns_empty(self) -> None:
        indices, error = apply_jq_filter(".level", [])
        assert indices == []
        assert error is None

    def test_results_with_only_none_and_false_excludes_entry(self) -> None:
        entries = [{"a": None, "b": False}]
        indices, _ = apply_jq_filter(".a, .b", entries)
        assert indices == []

    def test_results_with_one_truthy_includes_entry(self) -> None:
        entries = [{"a": None, "b": "value"}]
        indices, _ = apply_jq_filter(".a, .b", entries)
        assert indices == [0]

    @pytest.mark.parametrize(
        "entry,path",
        [
            ({"count": 0}, ".count"),
            ({"items": []}, ".items"),
            ({"meta": {}}, ".meta"),
            ({"s": ""}, ".s"),
        ],
    )
    def test_non_null_non_false_values_are_truthy(
        self, entry: dict[str, Any], path: str
    ) -> None:
        indices, _ = apply_jq_filter(path, [entry])
        assert indices == [0]

    def test_empty_results_excludes_entry(self) -> None:
        entries = [{"a": 1}]
        indices, _ = apply_jq_filter(".missing // empty", entries)
        assert indices == []

    def test_per_entry_value_error_skipped(self) -> None:
        entries = [
            {"a": "10"},
            {"a": "not-a-number"},
            {"a": "20"},
        ]
        indices, error = apply_jq_filter(".a | tonumber", entries)
        assert indices == [0, 2]
        assert error is None

    def test_multi_result_filter_includes_when_any_truthy(self) -> None:
        entries = [{"tags": [None, False, "x"]}]
        indices, _ = apply_jq_filter(".tags[]", entries)
        assert indices == [0]

    def test_multi_result_filter_excludes_when_all_falsy(self) -> None:
        entries = [{"tags": [None, False, None]}]
        indices, _ = apply_jq_filter(".tags[]", entries)
        assert indices == []

    def test_indices_preserve_input_order(self) -> None:
        entries = [
            {"keep": True},
            {"keep": False},
            {"keep": True},
            {"keep": False},
            {"keep": True},
        ]
        indices, _ = apply_jq_filter(".keep", entries)
        assert indices == [0, 2, 4]


class TestApplyFilterTree:
    def test_empty_tree_returns_all_indices(self) -> None:
        entries = [{"a": i} for i in range(5)]
        indices, error = apply_filter_tree(FilterGroup(), entries)
        assert indices == [0, 1, 2, 3, 4]
        assert error is None

    def test_empty_tree_does_not_invoke_jq(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[str] = []

        def spy(expression: str, entries: list[dict[str, Any]]) -> Any:
            del entries  # unused
            calls.append(expression)
            raise AssertionError("jq should not be invoked for an empty tree")

        monkeypatch.setattr("jnav.filtering.apply_jq_filter", spy)
        apply_filter_tree(FilterGroup(), [{"a": 1}])
        assert calls == []

    def test_single_leaf_delegates_to_jq(self) -> None:
        entries = [
            {"level": "INFO"},
            {"level": "ERROR"},
            {"level": "INFO"},
        ]
        root = FilterGroup(children=[Filter(expr='.level == "ERROR"')])
        indices, error = apply_filter_tree(root, entries)
        assert indices == [1]
        assert error is None

    def test_fully_disabled_returns_all_indices(self) -> None:
        entries = [{"a": 1}, {"a": 2}]
        root = FilterGroup(
            children=[Filter(expr=".a", enabled=False)],
        )
        indices, error = apply_filter_tree(root, entries)
        assert indices == [0, 1]
        assert error is None

    def test_negated_root_group(self) -> None:
        entries = [
            {"level": "INFO"},
            {"level": "ERROR"},
            {"level": "INFO"},
        ]
        root = FilterGroup(
            negated=True,
            children=[Filter(expr='.level == "ERROR"')],
        )
        indices, error = apply_filter_tree(root, entries)
        assert indices == [0, 2]
        assert error is None


class TestCheckFilterWarning:
    @pytest.mark.parametrize("op", ["=", "+=", "-=", "|="])
    def test_warns_on_assignment_operator(self, op: str) -> None:
        assert check_filter_warning(f".a {op} 1") is not None

    @pytest.mark.parametrize("op", ["==", "!=", "<=", ">="])
    def test_no_warning_on_comparison_operator(self, op: str) -> None:
        assert check_filter_warning(f".a {op} 1") is None

    def test_no_warning_on_empty_expression(self) -> None:
        assert check_filter_warning("") is None

    def test_no_warning_on_equality_without_spaces(self) -> None:
        assert check_filter_warning(".a==1") is None

    def test_no_warning_on_equals_inside_string_literal(self) -> None:
        assert check_filter_warning('.msg == "a=b"') is None


class TestGetNested:
    def test_simple_field(self) -> None:
        assert get_nested({"level": "INFO"}, ".level") == "INFO"

    def test_nested_field(self) -> None:
        assert get_nested({"a": {"b": 1}}, ".a.b") == 1

    def test_missing_field_returns_none(self) -> None:
        assert get_nested({"a": 1}, ".missing") is None

    def test_iteration_with_multiple_results_returns_list(self) -> None:
        assert get_nested({"tags": [1, 2, 3]}, ".tags[]") == [1, 2, 3]

    def test_iteration_with_single_result_returns_scalar(self) -> None:
        assert get_nested({"tags": [42]}, ".tags[]") == 42

    def test_iteration_with_no_results_returns_empty_list(self) -> None:
        assert get_nested({"tags": []}, ".tags[]") == []

    def test_invalid_jq_returns_none(self) -> None:
        assert get_nested({"a": 1}, ".[") is None

    def test_identity_path_returns_entry(self) -> None:
        entry = {"a": 1}
        assert get_nested(entry, ".") == entry

    def test_empty_path_returns_none(self) -> None:
        assert get_nested({"a": 1}, "") is None

    def test_index_into_scalar_returns_none(self) -> None:
        assert get_nested({"a": 1}, ".a.b") is None

    def test_string_literal_containing_brackets(self) -> None:
        result = get_nested({"msg": "hello[]"}, '.msg | contains("[]")')
        assert result is True


class TestJqValueLiteral:
    def test_string_is_quoted(self) -> None:
        assert jq_value_literal("hello") == '"hello"'

    def test_string_with_quotes_is_escaped(self) -> None:
        literal = jq_value_literal('he said "hi"')
        assert json.loads(literal) == 'he said "hi"'

    def test_none(self) -> None:
        assert jq_value_literal(None) == "null"

    def test_int(self) -> None:
        assert jq_value_literal(42) == "42"

    def test_float_round_trips_through_jq(self) -> None:
        literal = jq_value_literal(3.14)
        assert jq.compile(literal).input_value(None).first() == 3.14

    def test_list_round_trips_through_json(self) -> None:
        literal = jq_value_literal([1, "a"])
        assert json.loads(literal) == [1, "a"]

    def test_dict_round_trips_through_json(self) -> None:
        literal = jq_value_literal({"a": 1})
        assert json.loads(literal) == {"a": 1}

    def test_bool_serialises_as_keyword_not_number(self) -> None:
        assert jq_value_literal(True) == "true"
        assert jq_value_literal(False) == "false"

    def test_nan_raises(self) -> None:
        with pytest.raises(ValueError):
            jq_value_literal(float("nan"))

    def test_inf_raises(self) -> None:
        with pytest.raises(ValueError):
            jq_value_literal(float("inf"))

    @given(
        st.one_of(
            st.text(),
            st.integers(min_value=-(10**9), max_value=10**9),
            st.floats(allow_nan=False, allow_infinity=False),
            st.booleans(),
            st.none(),
        )
    )
    def test_property_round_trip_through_jq(self, value: object) -> None:
        literal = jq_value_literal(value)
        result = jq.compile(literal).input_value(None).first()
        assert result == value


class TestJqPathToStr:
    def test_empty(self) -> None:
        assert _jq_path_to_str([]) == ""

    def test_single_string_key_no_leading_dot(self) -> None:
        assert _jq_path_to_str(["a"]) == "a"

    def test_two_string_keys(self) -> None:
        assert _jq_path_to_str(["a", "b"]) == "a.b"

    def test_single_int_index(self) -> None:
        assert _jq_path_to_str([0]) == "[0]"

    def test_mixed_string_then_int_then_string(self) -> None:
        assert _jq_path_to_str(["a", 0, "b"]) == "a[0].b"

    def test_int_first(self) -> None:
        assert _jq_path_to_str([0, "a"]) == "[0].a"

    @given(
        st.lists(
            st.one_of(
                st.from_regex(r"[a-z][a-z0-9_]{0,8}", fullmatch=True),
                st.integers(min_value=0, max_value=1000),
            ),
            min_size=1,
            max_size=6,
        )
    )
    def test_property_output_parses_as_jq_path(self, parts: list[str | int]) -> None:
        path = _jq_path_to_str(parts)
        jq.compile("." + path)

    @given(st.lists(st.text(min_size=1), min_size=1, max_size=6))
    def test_property_string_only_equivalent_to_dot_join(
        self, parts: list[str]
    ) -> None:
        assert _jq_path_to_str(parts) == ".".join(parts)


class TestResolveSelectedPaths:
    def test_trivial_column(self) -> None:
        result = resolve_selected_paths({"level"}, {"level": "INFO"})
        assert result == {"level"}

    def test_leading_dot_trivial(self) -> None:
        result = resolve_selected_paths({".level"}, {"level": "INFO"})
        assert result == {"level"}

    def test_simple_iteration(self) -> None:
        result = resolve_selected_paths({".tags[]"}, {"tags": ["a", "b", "c"]})
        assert result == {"tags[0]", "tags[1]", "tags[2]"}

    def test_iteration_with_pipe_into_field(self) -> None:
        result = resolve_selected_paths(
            {".items[] | .name"},
            {"items": [{"name": "x"}, {"name": "y"}]},
        )
        assert result == {"items[0].name", "items[1].name"}

    def test_pipe_with_dict_expansion(self) -> None:
        # When `path(...)` wrapping fails (constructed object is not
        # path-addressable) but the base expression is, fall back to
        # base + dict-key combination.
        result = resolve_selected_paths(
            {".items[] | {a: .x, b: .y}"},
            {"items": [{"x": 1, "y": 2}]},
        )
        assert "items[0].a" in result
        assert "items[0].b" in result

    def test_invalid_jq_falls_back_to_raw_column(self) -> None:
        col = ".items[] |"
        result = resolve_selected_paths({col}, {"a": 1})
        assert result == {col}

    def test_multiple_columns_mixed(self) -> None:
        result = resolve_selected_paths(
            {".level", ".tags[]"},
            {"level": "INFO", "tags": ["a", "b"]},
        )
        assert result == {"level", "tags[0]", "tags[1]"}

    def test_empty_columns(self) -> None:
        assert resolve_selected_paths(set(), {"a": 1}) == set()


class TestBuildExpression:
    def test_empty_root(self) -> None:
        assert build_expression(FilterGroup()) is None

    def test_single_leaf(self) -> None:
        root = FilterGroup(children=[Filter(expr=".a")])
        assert build_expression(root) == ".a"

    def test_two_and_leaves(self) -> None:
        root = FilterGroup(children=[Filter(expr=".a"), Filter(expr=".b")])
        assert build_expression(root) == ".a and .b"

    def test_or_group(self) -> None:
        root = FilterGroup(
            operator="or",
            children=[Filter(expr=".a"), Filter(expr=".b")],
        )
        assert build_expression(root) == ".a or .b"

    def test_nested_or_inside_and(self) -> None:
        root = FilterGroup(
            children=[
                Filter(expr=".a"),
                FilterGroup(
                    operator="or", children=[Filter(expr=".b"), Filter(expr=".c")]
                ),
            ]
        )
        assert build_expression(root) == ".a and (.b or .c)"

    def test_nested_and_inside_or(self) -> None:
        root = FilterGroup(
            operator="or",
            children=[
                FilterGroup(children=[Filter(expr=".a"), Filter(expr=".b")]),
                Filter(expr=".c"),
            ],
        )
        assert build_expression(root) == "(.a and .b) or .c"

    def test_negated_leaf(self) -> None:
        root = FilterGroup(children=[Filter(expr=".a", negated=True)])
        assert build_expression(root) == ".a | not"

    def test_negated_leaf_with_pipe(self) -> None:
        root = FilterGroup(
            children=[
                Filter(expr='.msg | contains("slow")', negated=True),
            ]
        )
        assert build_expression(root) == '.msg | contains("slow") | not'

    def test_negated_leaf_combined_with_and(self) -> None:
        root = FilterGroup(
            children=[
                Filter(expr='.level == "INFO"'),
                Filter(expr='.msg | contains("slow")', negated=True),
            ]
        )
        assert build_expression(root) == (
            '.level == "INFO" and (.msg | contains("slow") | not)'
        )

    def test_negated_leaf_with_or_in_expr(self) -> None:
        root = FilterGroup(
            children=[
                Filter(expr=".a or .b", negated=True),
            ]
        )
        assert build_expression(root) == ".a or .b | not"

    def test_negated_group(self) -> None:
        root = FilterGroup(
            negated=True,
            children=[Filter(expr=".a"), Filter(expr=".b")],
        )
        assert build_expression(root) == "(.a and .b) | not"

    def test_disabled_leaf_excluded(self) -> None:
        root = FilterGroup(
            children=[
                Filter(expr=".a"),
                Filter(expr=".b", enabled=False),
            ]
        )
        assert build_expression(root) == ".a"

    def test_disabled_group_excluded(self) -> None:
        root = FilterGroup(
            children=[
                Filter(expr=".a"),
                FilterGroup(operator="or", enabled=False, children=[Filter(expr=".b")]),
            ]
        )
        assert build_expression(root) == ".a"

    def test_subgroup_with_pipe_and_disabled_child(self) -> None:
        root = FilterGroup(
            children=[
                Filter(expr=".metadata != null"),
                FilterGroup(
                    operator="and",
                    children=[
                        Filter(expr='.metadata.host | contains("user")'),
                        Filter(expr='.level == "ERROR"', enabled=False),
                    ],
                ),
            ]
        )
        assert build_expression(root) == (
            '.metadata != null and (.metadata.host | contains("user"))'
        )

    def test_all_disabled_returns_none(self) -> None:
        root = FilterGroup(children=[Filter(expr=".a", enabled=False)])
        assert build_expression(root) is None

    def test_disabled_root_returns_none(self) -> None:
        root = FilterGroup(
            enabled=False,
            children=[Filter(expr=".a")],
        )
        assert build_expression(root) is None

    def test_empty_child_group_skipped(self) -> None:
        root = FilterGroup(
            children=[
                Filter(expr=".a"),
                FilterGroup(operator="or"),
            ]
        )
        assert build_expression(root) == ".a"

    def test_deeply_nested(self) -> None:
        root = FilterGroup(
            operator="or",
            children=[
                FilterGroup(children=[Filter(expr=".a"), Filter(expr=".b")]),
                FilterGroup(children=[Filter(expr=".c"), Filter(expr=".d")]),
            ],
        )
        assert build_expression(root) == "(.a and .b) or (.c and .d)"

    def test_or_root_with_and_subgroup_and_leaf(self) -> None:
        root = FilterGroup(
            operator="or",
            children=[
                FilterGroup(
                    operator="and",
                    children=[
                        Filter(expr='.level == "WARNING"'),
                        Filter(expr='.msg | contains("slow")'),
                    ],
                ),
                Filter(expr='.level == "INFO"'),
            ],
        )
        assert build_expression(root) == (
            '(.level == "WARNING" and (.msg | contains("slow"))) or .level == "INFO"'
        )


_LEAF_EXPRS = [
    ".a",
    ".b",
    ".level",
    '.level == "INFO"',
    ".count > 0",
    '.msg | contains("x")',
]


def _filter_node_strategy() -> st.SearchStrategy[Any]:
    leaf = st.builds(
        Filter,
        expr=st.sampled_from(_LEAF_EXPRS),
        enabled=st.booleans(),
        negated=st.booleans(),
    )
    return st.recursive(
        leaf,
        lambda children: st.builds(
            FilterGroup,
            operator=st.sampled_from(["and", "or"]),
            enabled=st.booleans(),
            negated=st.booleans(),
            children=st.lists(children, min_size=0, max_size=3),
        ),
        max_leaves=8,
    )


class TestBuildExpressionProperties:
    @given(_filter_node_strategy())
    def test_built_expression_is_compilable(self, node: Any) -> None:
        if isinstance(node, Filter):
            root = FilterGroup(children=[node])
        else:
            root = node
        expr = build_expression(root)
        if expr is not None:
            jq.compile(expr)

    @given(_filter_node_strategy())
    def test_disabling_all_children_equals_disabling_group(self, node: Any) -> None:
        assume(isinstance(node, FilterGroup) and node.children)
        all_children_disabled = node.model_copy(
            update={
                "children": [
                    c.model_copy(update={"enabled": False}) for c in node.children
                ]
            }
        )
        group_disabled = node.model_copy(update={"enabled": False})
        assert build_expression(all_children_disabled) == build_expression(
            group_disabled
        )


class TestTextSearchExpr:
    @pytest.mark.parametrize(
        "term,entry,expected",
        [
            ("error", {"msg": "an error occurred"}, True),
            ("error", {"msg": "all good"}, False),
            ("Error", {"msg": "an ERROR occurred"}, True),
            ("error", {"msg": "ERROR"}, True),
            ("slow", {"nested": {"detail": "slow response"}}, True),
            ("slow", {"msg": 42}, False),
        ],
    )
    def test_matches_entry(
        self, term: str, entry: dict[str, Any], expected: bool
    ) -> None:
        expr = text_search_expr(term)
        result = jq.compile(expr).input_value(entry).first()
        assert result is expected

    def test_escapes_quotes(self) -> None:
        expr = text_search_expr('say "hi"')
        result = jq.compile(expr).input_value({"msg": 'go on, say "hi"'}).first()
        assert result is True

    def test_escapes_backslash(self) -> None:
        expr = text_search_expr("a\\b")
        result = jq.compile(expr).input_value({"msg": "path a\\b here"}).first()
        assert result is True
