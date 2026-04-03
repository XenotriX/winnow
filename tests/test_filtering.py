from jnav.filtering import text_search_expr


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
