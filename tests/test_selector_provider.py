import pytest
import pytest_asyncio

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

        assert sp.selectors == [{"path": "data.role", "enabled": True}]
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

        assert [s["path"] for s in sp.selectors] == ["a", "b", "c"]

    @pytest.mark.asyncio
    async def test_toggle_selector(self, sp: SelectorProvider) -> None:
        await sp.add_selector("data.role")

        events, collect = make_signal_collector()
        await sp.on_change.subscribe_async(collect)
        await sp.toggle_selector(0)

        assert sp.selectors[0]["enabled"] is False
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_remove_selector(self, sp: SelectorProvider) -> None:
        await sp.add_selector("a")
        await sp.add_selector("b")

        events, collect = make_signal_collector()
        await sp.on_change.subscribe_async(collect)
        await sp.remove_selector(0)

        assert len(sp.selectors) == 1
        assert sp.selectors[0]["path"] == "b"
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_remove_selector_by_path(self, sp: SelectorProvider) -> None:
        await sp.add_selector("a")
        await sp.add_selector("b")

        await sp.remove_selector_by_path("a")

        assert [s["path"] for s in sp.selectors] == ["b"]

    @pytest.mark.asyncio
    async def test_edit_selector(self, sp: SelectorProvider) -> None:
        await sp.add_selector("old.path")

        events, collect = make_signal_collector()
        await sp.on_change.subscribe_async(collect)
        await sp.edit_selector(0, "new.path")

        assert sp.selectors[0]["path"] == "new.path"
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_set_selectors(self, sp: SelectorProvider) -> None:
        selectors: list[Selector] = [
            {"path": "a", "enabled": True},
            {"path": "b", "enabled": False},
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


class TestDerivedProperties:
    @pytest.mark.asyncio
    async def test_active_selectors(self, sp: SelectorProvider) -> None:
        await sp.add_selector("a")
        await sp.add_selector("b")
        await sp.toggle_selector(1)

        assert sp.active_selectors == {"a"}

    @pytest.mark.asyncio
    async def test_has_selector(self, sp: SelectorProvider) -> None:
        await sp.add_selector("a")

        assert sp.has_selector("a")
        assert not sp.has_selector("b")
