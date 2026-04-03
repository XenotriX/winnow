import asyncio

import aioreactive as rx
import pytest

from jnav.buffer import buffer_time_or_count
from jnav.filter_provider import FilterProvider
from jnav.log_model import LogModel
from jnav.parsing import ParsedEntry, parse_line, preprocess_entry
from jnav.store import Store

from tests.conftest import SAMPLE_LINES, fake_line_reader, make_collector


class TestRxPipe:
    @pytest.mark.asyncio
    async def test_pipe_parses_and_filters(self) -> None:
        """The rx.pipe chain should parse lines, drop errors, and preprocess."""
        lines = fake_line_reader(
            [
                '{"level": "INFO", "msg": "ok"}',
                "not-json",
                '{"level": "ERROR", "msg": "fail"}',
            ]
        )

        pipe = rx.pipe(
            rx.from_async_iterable(lines),
            rx.map(lambda line: parse_line(line)),
            rx.filter(lambda result: result.is_ok()),
            rx.map(lambda entry: preprocess_entry(entry.ok)),
        )

        results: list[ParsedEntry] = []
        async for item in rx.to_async_iterable(pipe):
            results.append(item)

        assert len(results) == 2
        assert results[0].expanded["level"] == "INFO"
        assert results[1].expanded["level"] == "ERROR"


class TestFullPipeline:
    @pytest.mark.asyncio
    async def test_lines_reach_store_via_observable(self) -> None:
        """End-to-end: raw JSON lines -> rx.pipe -> buffer -> store."""
        lines = fake_line_reader(SAMPLE_LINES)

        entry_stream = rx.from_async_iterable(
            buffer_time_or_count(
                rx.pipe(
                    rx.from_async_iterable(lines),
                    rx.map(lambda line: parse_line(line)),
                    rx.filter(lambda result: result.is_ok()),
                    rx.map(lambda entry: preprocess_entry(entry.ok)),
                ),
                max_count=100,
                timeout=0.1,
            )
        )

        store = Store()

        collected: list[list[ParsedEntry]] = []
        async for batch in rx.to_async_iterable(entry_stream):
            collected.append(batch)
            await store.append_entries(batch)

        assert len(store) == len(SAMPLE_LINES)
        assert store.get(0).entry.expanded["message"] == "hello"
        assert store.get(1).entry.expanded["message"] == "boom"

    @pytest.mark.asyncio
    async def test_lines_reach_model_via_subscribe(self) -> None:
        """End-to-end with subscribe_async: lines -> store -> model."""
        lines = fake_line_reader(SAMPLE_LINES)

        entry_stream = rx.from_async_iterable(
            buffer_time_or_count(
                rx.pipe(
                    rx.from_async_iterable(lines),
                    rx.map(lambda line: parse_line(line)),
                    rx.filter(lambda result: result.is_ok()),
                    rx.map(lambda entry: preprocess_entry(entry.ok)),
                ),
                max_count=100,
                timeout=0.1,
            )
        )

        store = Store()
        model = LogModel(store=store, filter_provider=FilterProvider())
        await model.start()

        model_received, collect = make_collector()
        await model.on_append.subscribe_async(collect)

        await entry_stream.subscribe_async(store.append_entries)

        # Give the background tasks time to complete
        await asyncio.sleep(0.5)

        assert len(store) == len(SAMPLE_LINES), (
            f"Store has {len(store)} entries, expected {len(SAMPLE_LINES)}"
        )
        assert len(model_received) > 0, "Model.on_append never fired"
        total = sum(len(b) for b in model_received)
        assert total == len(SAMPLE_LINES), (
            f"Model received {total} entries, expected {len(SAMPLE_LINES)}"
        )

    @pytest.mark.asyncio
    async def test_late_subscriber_sees_existing_entries_via_model_all(self) -> None:
        """A subscriber that joins after data has flowed can catch up via model.all()."""
        store = Store()
        model = LogModel(store=store, filter_provider=FilterProvider())
        await model.start()

        entries = [preprocess_entry({"i": i}) for i in range(5)]
        await store.append_entries(entries)

        # Late subscriber: missed the on_append emission
        late_received, collect = make_collector()
        await model.on_append.subscribe_async(collect)

        # on_append won't replay, so late_received is empty
        assert len(late_received) == 0

        # But model.all() has everything
        assert len(model.all()) == 5
        assert [ie.entry for ie in model.all()] == entries
