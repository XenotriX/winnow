from jnav.filtering import (
    Filter,
    FilterGroup,
    build_expression,
    text_search_expr,
)



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
        root = FilterGroup(children=[
            Filter(expr=".a"),
            FilterGroup(operator="or", children=[Filter(expr=".b"), Filter(expr=".c")]),
        ])
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
        root = FilterGroup(children=[
            Filter(expr='.msg | contains("slow")', negated=True),
        ])
        assert build_expression(root) == '.msg | contains("slow") | not'

    def test_negated_leaf_combined_with_and(self) -> None:
        root = FilterGroup(children=[
            Filter(expr='.level == "INFO"'),
            Filter(expr='.msg | contains("slow")', negated=True),
        ])
        assert build_expression(root) == (
            '.level == "INFO" and (.msg | contains("slow") | not)'
        )

    def test_negated_leaf_with_or_in_expr(self) -> None:
        root = FilterGroup(children=[
            Filter(expr=".a or .b", negated=True),
        ])
        assert build_expression(root) == ".a or .b | not"

    def test_negated_group(self) -> None:
        root = FilterGroup(
            negated=True,
            children=[Filter(expr=".a"), Filter(expr=".b")],
        )
        assert build_expression(root) == "(.a and .b) | not"

    def test_disabled_leaf_excluded(self) -> None:
        root = FilterGroup(children=[
            Filter(expr=".a"),
            Filter(expr=".b", enabled=False),
        ])
        assert build_expression(root) == ".a"

    def test_disabled_group_excluded(self) -> None:
        root = FilterGroup(children=[
            Filter(expr=".a"),
            FilterGroup(operator="or", enabled=False, children=[Filter(expr=".b")]),
        ])
        assert build_expression(root) == ".a"

    def test_subgroup_with_pipe_and_disabled_child(self) -> None:
        root = FilterGroup(children=[
            Filter(expr=".metadata != null"),
            FilterGroup(
                operator="and",
                children=[
                    Filter(expr='.metadata.host | contains("user")'),
                    Filter(expr='.level == "ERROR"', enabled=False),
                ],
            ),
        ])
        assert build_expression(root) == (
            '.metadata != null and (.metadata.host | contains("user"))'
        )

    def test_all_disabled_returns_none(self) -> None:
        root = FilterGroup(children=[Filter(expr=".a", enabled=False)])
        assert build_expression(root) is None

    def test_empty_child_group_skipped(self) -> None:
        root = FilterGroup(children=[
            Filter(expr=".a"),
            FilterGroup(operator="or"),
        ])
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


class TestTextSearchExpr:
    def test_simple_term(self) -> None:
        expr = text_search_expr("error")
        assert 'contains("error")' in expr

    def test_case_insensitive(self) -> None:
        expr = text_search_expr("Error")
        assert 'contains("error")' in expr

    def test_escapes_backslash(self) -> None:
        expr = text_search_expr("a\\b")
        assert "a\\\\b" in expr

    def test_escapes_quotes(self) -> None:
        expr = text_search_expr('say "hi"')
        assert r"say \"hi\"" in expr
