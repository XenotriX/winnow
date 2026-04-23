import json

from jnav.json_model import ExpandedString
from jnav.parsing import ParsedEntry, parse_entry


class TestParseEntry:
    def test_valid_json_object(self) -> None:
        result = parse_entry('{"key": "value"}')
        assert isinstance(result, ParsedEntry)
        assert result.expanded == {"key": "value"}
        assert result.raw == '{"key": "value"}'

    def test_invalid_json(self) -> None:
        assert parse_entry("not json") is None

    def test_empty_line(self) -> None:
        assert parse_entry("") is None

    def test_json_array(self) -> None:
        result = parse_entry("[1, 2, 3]")
        assert result is not None
        assert result.expanded == [1, 2, 3]

    def test_whitespace_stripped(self) -> None:
        result = parse_entry('  {"a": 1}  \n')
        assert result is not None
        assert result.expanded == {"a": 1}
        assert result.raw == '{"a": 1}'

    def test_basic_entry_has_no_expanded_strings(self) -> None:
        result = parse_entry('{"level": "INFO", "message": "hello"}')
        assert result is not None
        assert result.expanded == {"level": "INFO", "message": "hello"}

    def test_nested_json_string_is_wrapped(self) -> None:
        inner = json.dumps({"a": 1, "b": 2})
        result = parse_entry(json.dumps({"data": inner}))
        assert result is not None
        assert isinstance(result.expanded, dict)
        data = result.expanded["data"]
        assert isinstance(data, ExpandedString)
        assert data.original == inner
        assert data.parsed == {"a": 1, "b": 2}

    def test_non_json_string_left_alone(self) -> None:
        result = parse_entry('{"msg": "plain text"}')
        assert result is not None
        assert isinstance(result.expanded, dict)
        assert result.expanded["msg"] == "plain text"

    def test_empty_json_string_expanded(self) -> None:
        result = parse_entry('{"a": "{}", "b": "[]"}')
        assert result is not None
        assert isinstance(result.expanded, dict)
        assert isinstance(result.expanded["a"], ExpandedString)
        assert isinstance(result.expanded["b"], ExpandedString)

    def test_top_level_int(self) -> None:
        result = parse_entry("42")
        assert result is not None
        assert type(result.expanded) is int
        assert result.expanded == 42

    def test_top_level_string(self) -> None:
        result = parse_entry('"hello"')
        assert result is not None
        assert type(result.expanded) is str
        assert result.expanded == "hello"

    def test_top_level_float(self) -> None:
        result = parse_entry("3.14")
        assert result is not None
        assert type(result.expanded) is float
        assert result.expanded == 3.14

    def test_top_level_bool(self) -> None:
        result = parse_entry("true")
        assert result is not None
        assert type(result.expanded) is bool
        assert result.expanded is True

    def test_top_level_null(self) -> None:
        result = parse_entry("null")
        assert result is not None
        assert result.expanded is None

    def test_top_level_json_string(self) -> None:
        inner = '{"x": 1}'
        outer = json.dumps(inner)
        result = parse_entry(outer)
        assert result is not None
        assert isinstance(result.expanded, ExpandedString)
        assert result.expanded.original == inner
        assert result.expanded.parsed == {"x": 1}
