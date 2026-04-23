import pytest
import pytest_asyncio

from jnav.json_model import JsonValue
from jnav.selector_provider import Selector, SelectorProvider

from .conftest import make_signal_collector


@pytest_asyncio.fixture
async def sp() -> SelectorProvider:
    return SelectorProvider()


class TestSelectorMutations:
    @pytest.mark.asyncio
    async def test_add_selector(self, sp: SelectorProvider) -> None:
        events, collect = make_signal_collector()
        await sp.on_change.subscribe_async(collect)

        await sp.add_selector("data.role")

        assert sp.selectors == [Selector(path="data.role", enabled=True)]
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_add_duplicate_is_allowed(self, sp: SelectorProvider) -> None:
        await sp.add_selector("data.role")
        await sp.add_selector("data.role")

        assert len(sp.selectors) == 2

    @pytest.mark.asyncio
    async def test_insert_selector(self, sp: SelectorProvider) -> None:
        await sp.add_selector("a")
        await sp.add_selector("c")

        await sp.insert_selector(1, "b")

        assert [s.path for s in sp.selectors] == ["a", "b", "c"]

    @pytest.mark.asyncio
    async def test_toggle_selector(self, sp: SelectorProvider) -> None:
        await sp.add_selector("data.role")

        events, collect = make_signal_collector()
        await sp.on_change.subscribe_async(collect)
        await sp.toggle_selector(0)

        assert sp.selectors[0].enabled is False
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_remove_selector(self, sp: SelectorProvider) -> None:
        await sp.add_selector("a")
        await sp.add_selector("b")

        events, collect = make_signal_collector()
        await sp.on_change.subscribe_async(collect)
        await sp.remove_selector(0)

        assert len(sp.selectors) == 1
        assert sp.selectors[0].path == "b"
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_remove_selector_by_path(self, sp: SelectorProvider) -> None:
        await sp.add_selector("a")
        await sp.add_selector("b")

        await sp.remove_selector_by_path("a")

        assert [s.path for s in sp.selectors] == ["b"]

    @pytest.mark.asyncio
    async def test_edit_selector(self, sp: SelectorProvider) -> None:
        await sp.add_selector("old.path")

        events, collect = make_signal_collector()
        await sp.on_change.subscribe_async(collect)
        await sp.edit_selector(0, "new.path")

        assert sp.selectors[0].path == "new.path"
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_set_selectors(self, sp: SelectorProvider) -> None:
        selectors: list[Selector] = [
            Selector(path="a", enabled=True),
            Selector(path="b", enabled=False),
        ]

        events, collect = make_signal_collector()
        await sp.on_change.subscribe_async(collect)
        await sp.set_selectors(selectors)

        assert sp.selectors == selectors
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_clear_selectors(self, sp: SelectorProvider) -> None:
        await sp.add_selector("a")
        await sp.add_selector("b")

        events, collect = make_signal_collector()
        await sp.on_change.subscribe_async(collect)
        await sp.clear_selectors()

        assert sp.selectors == []
        assert len(events) == 1


class TestSelectorResolve:
    def _sel(self, path: str) -> Selector:
        return Selector(path=path, enabled=True)

    def test_simple_field(self) -> None:
        assert self._sel(".level").resolve({"level": "INFO"}) == "INFO"

    def test_nested_field(self) -> None:
        assert self._sel(".a.b").resolve({"a": {"b": 1}}) == 1

    def test_missing_field_returns_none(self) -> None:
        assert self._sel(".missing").resolve({"a": 1}) is None

    def test_iteration_with_multiple_results_returns_list(self) -> None:
        assert self._sel(".tags[]").resolve({"tags": [1, 2, 3]}) == [1, 2, 3]

    def test_iteration_with_single_result_returns_scalar(self) -> None:
        assert self._sel(".tags[]").resolve({"tags": [42]}) == 42

    def test_iteration_with_no_results_returns_empty_list(self) -> None:
        assert self._sel(".tags[]").resolve({"tags": []}) == []

    def test_invalid_jq_returns_none(self) -> None:
        assert self._sel(".[").resolve({"a": 1}) is None

    def test_identity_path_returns_entry(self) -> None:
        entry: JsonValue = {"a": 1}
        assert self._sel(".").resolve(entry) == entry

    def test_empty_path_returns_none(self) -> None:
        assert self._sel("").resolve({"a": 1}) is None

    def test_index_into_scalar_returns_none(self) -> None:
        assert self._sel(".a.b").resolve({"a": 1}) is None

    def test_string_literal_containing_brackets(self) -> None:
        result = self._sel('.msg | contains("[]")').resolve({"msg": "hello[]"})
        assert result is True


class TestDerivedProperties:
    @pytest.mark.asyncio
    async def test_active_selectors(self, sp: SelectorProvider) -> None:
        await sp.add_selector("a")
        await sp.add_selector("b")
        await sp.toggle_selector(1)

        assert [s.path for s in sp.active_selectors] == ["a"]

    @pytest.mark.asyncio
    async def test_active_selectors_preserves_order(self, sp: SelectorProvider) -> None:
        await sp.add_selector("c")
        await sp.add_selector("a")
        await sp.add_selector("b")
        await sp.add_selector("skip")
        await sp.toggle_selector(3)

        assert [s.path for s in sp.active_selectors] == ["c", "a", "b"]

    @pytest.mark.asyncio
    async def test_has_selector(self, sp: SelectorProvider) -> None:
        await sp.add_selector("a")

        assert sp.has_selector("a")
        assert not sp.has_selector("b")
