from typing import Any

import pytest
import pytest_asyncio

from jnav.field_manager import FieldManager, FieldSelector
from jnav.parsing import preprocess_entry
from jnav.store import IndexedEntry

from .conftest import make_signal_collector


def _ie(index: int, data: dict[str, Any]) -> IndexedEntry:
    return IndexedEntry(index, preprocess_entry(data))


@pytest_asyncio.fixture
async def fm() -> FieldManager:
    return FieldManager()


class TestDiscover:
    def test_populates_all_fields(self, fm: FieldManager) -> None:
        fm.discover([_ie(0, {"level": "INFO", "message": "hi", "extra": 1})])

        assert "level" in fm.all_fields
        assert "message" in fm.all_fields
        assert "extra" in fm.all_fields

    def test_grows_incrementally(self, fm: FieldManager) -> None:
        fm.discover([_ie(0, {"a": 1})])
        fm.discover([_ie(1, {"a": 2, "b": 3})])

        assert fm.all_fields == ["a", "b"]

    def test_nested_dict_flattened(self, fm: FieldManager) -> None:
        fm.discover([_ie(0, {"data": {"host": "a", "pid": 1}, "level": "INFO"})])

        assert "data.host" in fm.all_fields
        assert "data.pid" in fm.all_fields
        assert "data" not in fm.all_fields

    def test_no_duplicates(self, fm: FieldManager) -> None:
        fm.discover([_ie(0, {"a": 1})])
        fm.discover([_ie(1, {"a": 2})])

        assert fm.all_fields.count("a") == 1

    def test_base_fields_set_on_first_discover(self, fm: FieldManager) -> None:
        fm.discover([_ie(0, {"ts": "2025-01-01", "level": "INFO", "message": "hi", "extra": 1})])

        assert fm.base_fields == ["ts", "level", "message"]

    def test_base_fields_not_overwritten_on_subsequent_discover(self, fm: FieldManager) -> None:
        fm.discover([_ie(0, {"level": "INFO"})])
        first_base = list(fm.base_fields)
        fm.discover([_ie(1, {"level": "INFO", "ts": "2025-01-01"})])

        assert fm.base_fields == first_base


class TestCustomFieldMutations:
    @pytest.mark.asyncio
    async def test_add_field(self, fm: FieldManager) -> None:
        events, collect = make_signal_collector()
        await fm.on_change.subscribe_async(collect)

        await fm.add_field("data.role")

        assert fm.custom_fields == [{"path": "data.role", "enabled": True}]
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_add_duplicate_is_noop(self, fm: FieldManager) -> None:
        await fm.add_field("data.role")

        events, collect = make_signal_collector()
        await fm.on_change.subscribe_async(collect)
        await fm.add_field("data.role")

        assert len(fm.custom_fields) == 1
        assert len(events) == 0

    @pytest.mark.asyncio
    async def test_toggle_field(self, fm: FieldManager) -> None:
        await fm.add_field("data.role")

        events, collect = make_signal_collector()
        await fm.on_change.subscribe_async(collect)
        await fm.toggle_field(0)

        assert fm.custom_fields[0]["enabled"] is False
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_remove_field(self, fm: FieldManager) -> None:
        await fm.add_field("a")
        await fm.add_field("b")

        events, collect = make_signal_collector()
        await fm.on_change.subscribe_async(collect)
        await fm.remove_field(0)

        assert len(fm.custom_fields) == 1
        assert fm.custom_fields[0]["path"] == "b"
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_edit_field(self, fm: FieldManager) -> None:
        await fm.add_field("old.path")

        events, collect = make_signal_collector()
        await fm.on_change.subscribe_async(collect)
        await fm.edit_field(0, "new.path")

        assert fm.custom_fields[0]["path"] == "new.path"
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_set_custom_fields(self, fm: FieldManager) -> None:
        fields: list[FieldSelector] = [
            {"path": "a", "enabled": True},
            {"path": "b", "enabled": False},
        ]

        events, collect = make_signal_collector()
        await fm.on_change.subscribe_async(collect)
        await fm.set_custom_fields(fields)

        assert fm.custom_fields == fields
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_clear_custom_fields(self, fm: FieldManager) -> None:
        await fm.add_field("a")
        await fm.add_field("b")

        events, collect = make_signal_collector()
        await fm.on_change.subscribe_async(collect)
        await fm.clear_custom_fields()

        assert fm.custom_fields == []
        assert len(events) == 1


class TestDerivedProperties:
    @pytest.mark.asyncio
    async def test_active_fields(self, fm: FieldManager) -> None:
        fm.discover([_ie(0, {"ts": "x", "level": "INFO", "message": "hi"})])
        await fm.add_field("extra.a")
        await fm.add_field("extra.b")
        await fm.toggle_field(1)

        assert fm.active_fields == ["ts", "level", "message", "extra.a"]

    @pytest.mark.asyncio
    async def test_custom_fields_set(self, fm: FieldManager) -> None:
        await fm.add_field("a")
        await fm.add_field("b")
        await fm.toggle_field(1)

        assert fm.custom_fields_set == {"a"}
