from typing import Any

import pytest
import pytest_asyncio

from jnav.field_manager import FieldManager, FieldSelector
from jnav.field_mapping import FieldMapping, TimestampField
from jnav.log_entry_item import format_timestamp
from jnav.store import IndexedEntry

from .conftest import make_entry, make_signal_collector


def _ie(index: int, data: dict[str, Any]) -> IndexedEntry:
    return IndexedEntry(index, make_entry(data))


@pytest_asyncio.fixture
async def fm() -> FieldManager:
    return FieldManager()


class TestDiscover:
    @pytest.mark.asyncio
    async def test_populates_all_fields(self, fm: FieldManager) -> None:
        await fm.discover([_ie(0, {"level": "INFO", "message": "hi", "extra": 1})])

        assert "level" in fm.all_fields
        assert "message" in fm.all_fields
        assert "extra" in fm.all_fields

    @pytest.mark.asyncio
    async def test_grows_incrementally(self, fm: FieldManager) -> None:
        await fm.discover([_ie(0, {"a": 1})])

        assert fm.all_fields == {"a"}

        await fm.discover([_ie(1, {"a": 2, "b": 3})])

        assert fm.all_fields == {"a", "b"}


class TestDiscoverMappingDetection:
    @pytest.mark.asyncio
    async def test_populates_mapping_from_known_names(self, fm: FieldManager) -> None:
        await fm.discover([
            _ie(0, {"ts": "2025-01-01T00:00:00", "level": "INFO", "message": "hi"})
        ])

        assert fm.mapping.timestamp == TimestampField(path="ts", format="iso8601")
        assert fm.mapping.level == "level"
        assert fm.mapping.message == "message"

    @pytest.mark.asyncio
    async def test_keeps_filling_missing_roles_across_batches(
        self, fm: FieldManager
    ) -> None:
        # First batch only has a timestamp field.
        await fm.discover([_ie(0, {"ts": "2025-01-01T00:00:00"})])
        assert fm.mapping.timestamp == TimestampField(path="ts", format="iso8601")
        assert fm.mapping.level is None
        assert fm.mapping.message is None

        # Second batch brings the missing roles along; detection fills them in.
        await fm.discover([_ie(1, {"level": "INFO", "message": "hi"})])
        assert fm.mapping.missing_roles() == []

    @pytest.mark.asyncio
    async def test_does_not_overwrite_already_detected_roles(
        self, fm: FieldManager
    ) -> None:
        # First batch picks up `@timestamp`.
        await fm.discover([_ie(0, {"@timestamp": "2025-01-01T00:00:00"})])
        assert fm.mapping.timestamp == TimestampField(
            path="@timestamp", format="iso8601"
        )

        # Second batch would have detected `ts` as a fallback, but the
        # timestamp role is already filled and must not be replaced.
        await fm.discover([_ie(1, {"ts": "2025-01-01T00:00:00"})])
        assert fm.mapping.timestamp == TimestampField(
            path="@timestamp", format="iso8601"
        )

    @pytest.mark.asyncio
    async def test_stops_once_mapping_is_complete(self, fm: FieldManager) -> None:
        await fm.discover([
            _ie(0, {"ts": "2025-01-01T00:00:00", "level": "INFO", "message": "hi"})
        ])
        first = fm.mapping
        assert first.missing_roles() == []

        # Subsequent batch should not change the mapping — even if it contains
        # higher-priority candidate names like `@timestamp`.
        await fm.discover([
            _ie(
                1,
                {
                    "@timestamp": "2025-01-01T00:00:00",
                    "severity": "WARN",
                    "msg": "hi",
                },
            )
        ])
        assert fm.mapping == first

    @pytest.mark.asyncio
    async def test_complete_set_mapping_suppresses_detection(
        self, fm: FieldManager
    ) -> None:
        preset = FieldMapping(
            timestamp=TimestampField(path="@timestamp", format="iso8601"),
            level="severity",
            message="@m",
        )
        await fm.set_mapping(preset)
        await fm.discover([
            _ie(0, {"ts": "2025-01-01T00:00:00", "level": "INFO", "message": "hi"})
        ])

        assert fm.mapping == preset

    @pytest.mark.asyncio
    async def test_partial_set_mapping_still_fills_remaining_roles(
        self, fm: FieldManager
    ) -> None:
        await fm.set_mapping(
            FieldMapping(timestamp=TimestampField(path="@timestamp", format="iso8601"))
        )
        await fm.discover([_ie(0, {"ts": "x", "level": "INFO", "message": "hi"})])

        assert fm.mapping.timestamp == TimestampField(
            path="@timestamp", format="iso8601"
        )
        assert fm.mapping.level == "level"
        assert fm.mapping.message == "message"

    @pytest.mark.asyncio
    async def test_empty_batch_does_not_trigger_detection(
        self, fm: FieldManager
    ) -> None:
        await fm.discover([])

        assert fm.mapping == FieldMapping()

    @pytest.mark.asyncio
    async def test_fires_on_change_when_detection_updates_mapping(
        self, fm: FieldManager
    ) -> None:
        events, collect = make_signal_collector()
        await fm.on_change.subscribe_async(collect)

        await fm.discover([
            _ie(0, {"ts": "2025-01-01T00:00:00", "level": "INFO", "message": "hi"})
        ])

        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_no_on_change_when_detection_is_noop(self, fm: FieldManager) -> None:
        events, collect = make_signal_collector()
        await fm.on_change.subscribe_async(collect)

        await fm.discover([_ie(0, {"weird": "value"})])

        assert len(events) == 0


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
        await fm.discover([_ie(0, {"ts": "x", "level": "INFO", "message": "hi"})])
        await fm.add_field("extra.a")
        await fm.add_field("extra.b")
        await fm.toggle_field(1)

        assert fm.active_fields == {"extra.a"}

    @pytest.mark.asyncio
    async def test_custom_fields_set(self, fm: FieldManager) -> None:
        await fm.add_field("a")
        await fm.add_field("b")
        await fm.toggle_field(1)

        assert fm.active_fields == {"a"}


class TestSetMapping:
    @pytest.mark.asyncio
    async def test_set_mapping_fires_on_change(self, fm: FieldManager) -> None:
        events, collect = make_signal_collector()
        await fm.on_change.subscribe_async(collect)

        await fm.set_mapping(
            FieldMapping(
                timestamp=TimestampField(path="ts", format="iso8601"),
                level="level",
                message="message",
            )
        )

        assert fm.mapping.timestamp == TimestampField(path="ts", format="iso8601")
        assert len(events) == 1


class TestKnownFormats:
    @pytest.mark.asyncio
    async def test_logstash_style(self, fm: FieldManager) -> None:
        await fm.discover_from_entry(
            {
                "@timestamp": "2025-01-01T00:00:00",
                "level": "INFO",
                "message": "hello",
            }
        )
        assert fm.mapping.timestamp == TimestampField(
            path="@timestamp", format="iso8601"
        )
        assert fm.mapping.level == "level"
        assert fm.mapping.message == "message"

    @pytest.mark.asyncio
    async def test_bunyan_style(self, fm: FieldManager) -> None:
        await fm.discover_from_entry(
            {"time": "2025-01-01T00:00:00", "level": 30, "msg": "hi"}
        )
        assert fm.mapping.timestamp == TimestampField(path="time", format="iso8601")
        assert fm.mapping.level == "level"
        assert fm.mapping.message == "msg"

    @pytest.mark.asyncio
    async def test_pino_epoch_ms(self, fm: FieldManager) -> None:
        await fm.discover_from_entry(
            {"time": 1_700_000_000_000, "level": 30, "msg": "hi"}
        )
        assert fm.mapping.timestamp == TimestampField(path="time", format="epoch_ms")

    @pytest.mark.asyncio
    async def test_zap_ts(self, fm: FieldManager) -> None:
        await fm.discover_from_entry(
            {"ts": "2025-01-01T00:00:00", "level": "info", "msg": "hi"}
        )
        assert fm.mapping.timestamp == TimestampField(path="ts", format="iso8601")

    @pytest.mark.asyncio
    async def test_serilog_style(self, fm: FieldManager) -> None:
        await fm.discover_from_entry(
            {"@t": "2025-01-01T00:00:00", "@l": "Warning", "@m": "hi"}
        )
        assert fm.mapping.timestamp == TimestampField(path="@t", format="iso8601")
        assert fm.mapping.level == "@l"
        assert fm.mapping.message == "@m"

    @pytest.mark.asyncio
    async def test_priority_prefers_earlier_candidate(
        self, fm: FieldManager
    ) -> None:
        await fm.discover_from_entry(
            {
                "@timestamp": "2025-01-01T00:00:00",
                "ts": "2025-01-01T00:00:00",
                "time": "2025-01-01T00:00:00",
                "level": "INFO",
                "message": "hi",
            }
        )
        # @timestamp has higher priority than ts/time
        assert fm.mapping.timestamp is not None
        assert fm.mapping.timestamp.path == "@timestamp"

    @pytest.mark.asyncio
    async def test_unknown_format_leaves_mapping_empty(
        self, fm: FieldManager
    ) -> None:
        await fm.discover_from_entry({"weird": "2025-01-01", "value": 42})
        assert fm.mapping == FieldMapping()


class TestDetectTimestampFormat:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (1_700_000_000, "epoch_s"),
            (1_700_000_000_000, "epoch_ms"),
            (1_700_000_000_000_000, "epoch_us"),
            (1_700_000_000_000_000_000, "epoch_ns"),
        ],
    )
    @pytest.mark.asyncio
    async def test_epoch_magnitude(
        self, fm: FieldManager, value: int, expected: str
    ) -> None:
        await fm.discover_from_entry({"ts": value})
        assert fm.mapping.timestamp is not None
        assert fm.mapping.timestamp.format == expected


class TestFormatTimestamp:
    def test_iso8601(self) -> None:
        assert format_timestamp("2025-01-01T10:30:45.123456", "iso8601") == (
            "10:30:45.123"
        )

    def test_epoch_s(self) -> None:
        # 2023-11-14 22:13:20 UTC
        assert format_timestamp(1_700_000_000, "epoch_s") == "22:13:20.000"

    def test_epoch_ms(self) -> None:
        assert format_timestamp(1_700_000_000_500, "epoch_ms") == "22:13:20.500"

    def test_epoch_us(self) -> None:
        assert format_timestamp(1_700_000_000_500_000, "epoch_us") == "22:13:20.500"

    def test_epoch_ns(self) -> None:
        assert format_timestamp(1_700_000_000_500_000_000, "epoch_ns") == (
            "22:13:20.500"
        )

    def test_invalid_iso8601_falls_back_to_string(self) -> None:
        assert format_timestamp("not a date", "iso8601") == "not a date"

    def test_invalid_epoch_value(self) -> None:
        assert format_timestamp("not a number", "epoch_s") == "not a number"


class TestFieldMappingRoundtrip:
    def test_full_roundtrip(self) -> None:
        mapping = FieldMapping(
            timestamp=TimestampField(path="@timestamp", format="iso8601"),
            level="severity",
            message="msg",
        )
        assert FieldMapping.model_validate(mapping.model_dump()) == mapping

    def test_empty_roundtrip(self) -> None:
        assert (
            FieldMapping.model_validate(FieldMapping().model_dump()) == FieldMapping()
        )

    def test_partial_roundtrip(self) -> None:
        mapping = FieldMapping(level="level")
        assert FieldMapping.model_validate(mapping.model_dump()) == mapping

    def test_missing_roles(self) -> None:
        assert FieldMapping().missing_roles() == ["timestamp", "level", "message"]
        assert FieldMapping(level="level").missing_roles() == [
            "timestamp",
            "message",
        ]
