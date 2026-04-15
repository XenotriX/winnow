# pyright: reportPrivateUsage=false, reportAttributeAccessIssue=false, reportUnknownMemberType=false, reportUninitializedInstanceVariable=false, reportReturnType=false

from dataclasses import FrozenInstanceError
from typing import TYPE_CHECKING, Any, ClassVar, override
from unittest.mock import AsyncMock, Mock

import pytest
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingsMap
from textual.events import Key
from textual.widgets import Static

from jnav.key_sequences import KeySequence, KeySequenceMixin


class _Harness(KeySequenceMixin):
    if TYPE_CHECKING:
        ancestors_with_self: list[Any]
        refresh_bindings: Any
        run_action: Any


def _make_harness(
    sequences: list[KeySequence],
    *,
    groups: dict[str, str] | None = None,
    seed_bindings: list[Binding] | None = None,
    ancestors: list[object] | None = None,
) -> _Harness:
    cls = type(
        "_TestHarness",
        (KeySequenceMixin,),
        {
            "SEQUENCES": sequences,
            "SEQUENCE_GROUPS": groups or {},
        },
    )
    harness = cls.__new__(cls)
    harness._bindings = BindingsMap(seed_bindings or [])
    harness.ancestors_with_self = [harness, *(ancestors or [])]
    harness.refresh_bindings = Mock()
    harness.run_action = AsyncMock(return_value=None)
    harness._seq_buffer = ""
    harness._seq_pending = False
    harness._seq_saved_bindings = None
    harness._seq_saved_ancestor_bindings = []
    harness._seq_keymap = {}
    harness._seq_lookup = {}
    harness._seq_prefixes = {}
    harness._seq_base_bindings = None
    harness._rebuild_sequences()
    return harness


def _make_ancestor(bindings: list[Binding] | None = None) -> Mock:
    ancestor = Mock()
    ancestor._bindings = BindingsMap(bindings or [])
    return ancestor


def _key(char: str) -> Key:
    return Key(char, char)


class TestKeySequenceDataclass:
    def test_defaults(self) -> None:
        seq = KeySequence("ff", "filter")
        assert seq.description == ""
        assert seq.show is True
        assert seq.id is None

    def test_is_frozen(self) -> None:
        seq = KeySequence("ff", "filter")
        with pytest.raises(FrozenInstanceError):
            seq.keys = "gg"  # type: ignore[misc]

    def test_equal_when_fields_match(self) -> None:
        a = KeySequence("ff", "filter", "desc")
        b = KeySequence("ff", "filter", "desc")
        assert a == b
        assert hash(a) == hash(b)


class TestBuildSeqLookup:
    def test_basic_mapping(self) -> None:
        seq1 = KeySequence("ff", "a")
        seq2 = KeySequence("fo", "b")
        h = _make_harness([seq1, seq2])
        assert h._seq_lookup == {"ff": seq1, "fo": seq2}

    def test_keymap_override_by_id(self) -> None:
        seq = KeySequence("ff", "filter", id="my_id")
        h = _make_harness([seq])
        h.set_sequence_keymap({"my_id": "gx"})
        assert "gx" in h._seq_lookup
        assert "ff" not in h._seq_lookup

    def test_id_not_in_keymap_falls_back_to_keys(self) -> None:
        seq = KeySequence("ff", "filter", id="my_id")
        h = _make_harness([seq])
        h.set_sequence_keymap({"other_id": "xx"})
        assert "ff" in h._seq_lookup

    def test_too_short_keys_raise(self) -> None:
        with pytest.raises(ValueError, match="at least 2 characters"):
            _make_harness([KeySequence("f", "action")])

    def test_keymap_override_to_single_char_raises(self) -> None:
        seq = KeySequence("ff", "filter", id="my_id")
        h = _make_harness([seq])
        with pytest.raises(ValueError, match="at least 2 characters"):
            h.set_sequence_keymap({"my_id": "x"})


class TestBuildSeqPrefixes:
    def test_shared_prefix_dedup(self) -> None:
        h = _make_harness(
            [KeySequence("ff", "a"), KeySequence("fo", "b")],
            groups={"f": "Filter"},
        )
        assert h._seq_prefixes == {"f": "Filter"}

    def test_prefix_without_group_has_empty_label(self) -> None:
        h = _make_harness([KeySequence("ff", "a")])
        assert h._seq_prefixes == {"f": ""}


class TestInjectPrefixBindings:
    def test_labelled_prefix_is_prepended(self) -> None:
        h = _make_harness(
            [KeySequence("ff", "a")],
            groups={"f": "Filter"},
            seed_bindings=[Binding("x", "other", "Other")],
        )
        keys = list(h._bindings.key_to_bindings)
        assert keys[0] == "f"
        assert keys[1] == "x"

    def test_labelled_prefix_replaces_existing_single_key_binding(self) -> None:
        h = _make_harness(
            [KeySequence("ff", "a")],
            groups={"f": "Filter"},
            seed_bindings=[Binding("f", "other", "Other")],
        )
        [binding] = h._bindings.key_to_bindings["f"]
        assert binding.action == "_seq_prefix_f"

    def test_unlabelled_prefix_removes_existing_binding_without_replacing(
        self,
    ) -> None:
        h = _make_harness(
            [KeySequence("ff", "a")],
            seed_bindings=[Binding("f", "other", "Other")],
        )
        assert "f" not in h._bindings.key_to_bindings

    def test_no_sequences_leaves_bindings_alone(self) -> None:
        h = _make_harness(
            [],
            seed_bindings=[Binding("x", "other", "Other")],
        )
        assert list(h._bindings.key_to_bindings) == ["x"]


class TestHandleSequenceKey:
    @pytest.mark.asyncio
    async def test_non_prefix_key_returns_false(self) -> None:
        h = _make_harness(
            [KeySequence("ff", "filter")],
            groups={"f": "Filter"},
        )
        event = _key("z")
        assert await h._handle_sequence_key(event) is False
        assert h._seq_pending is False

    @pytest.mark.asyncio
    async def test_prefix_key_starts_sequence(self) -> None:
        h = _make_harness(
            [KeySequence("ff", "filter")],
            groups={"f": "Filter"},
        )
        event = _key("f")
        assert await h._handle_sequence_key(event) is True
        assert h._seq_pending is True
        assert h._seq_buffer == "f"

    @pytest.mark.asyncio
    async def test_complete_two_char_sequence_runs_action(self) -> None:
        h = _make_harness(
            [KeySequence("ff", "filter")],
            groups={"f": "Filter"},
        )
        await h._handle_sequence_key(_key("f"))
        await h._handle_sequence_key(_key("f"))
        h.run_action.assert_awaited_once_with("filter")
        assert h._seq_pending is False
        assert h._seq_buffer == ""

    @pytest.mark.asyncio
    async def test_escape_cancels_pending(self) -> None:
        h = _make_harness(
            [KeySequence("ff", "filter")],
            groups={"f": "Filter"},
        )
        await h._handle_sequence_key(_key("f"))
        await h._handle_sequence_key(_key("escape"))
        h.run_action.assert_not_awaited()
        assert h._seq_pending is False

    @pytest.mark.asyncio
    async def test_unknown_continuation_resets_without_action(self) -> None:
        h = _make_harness(
            [KeySequence("ff", "filter"), KeySequence("fo", "other")],
            groups={"f": "Filter"},
        )
        await h._handle_sequence_key(_key("f"))
        await h._handle_sequence_key(_key("z"))
        h.run_action.assert_not_awaited()
        assert h._seq_pending is False

    @pytest.mark.asyncio
    async def test_three_char_sequence_requires_all_three(self) -> None:
        h = _make_harness(
            [KeySequence("gga", "go_a")],
            groups={"g": "Go"},
        )
        await h._handle_sequence_key(_key("g"))
        await h._handle_sequence_key(_key("g"))
        h.run_action.assert_not_awaited()
        assert h._seq_pending is True
        assert h._seq_buffer == "gg"
        await h._handle_sequence_key(_key("a"))
        h.run_action.assert_awaited_once_with("go_a")

    @pytest.mark.asyncio
    async def test_consumed_event_calls_prevent_default_and_stop(self) -> None:
        h = _make_harness(
            [KeySequence("ff", "filter")],
            groups={"f": "Filter"},
        )
        event = _key("f")
        event.prevent_default = Mock(wraps=event.prevent_default)
        event.stop = Mock(wraps=event.stop)
        await h._handle_sequence_key(event)
        event.prevent_default.assert_called_once()
        event.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_state_reset_before_action_runs(self) -> None:
        h = _make_harness(
            [KeySequence("ff", "filter")],
            groups={"f": "Filter"},
        )
        pre = h._bindings
        seen_state: dict[str, Any] = {}

        async def record_state(action: str) -> None:
            del action  # unused
            seen_state["pending"] = h._seq_pending
            seen_state["buffer"] = h._seq_buffer
            seen_state["bindings_is_pre"] = h._bindings is pre

        h.run_action = AsyncMock(side_effect=record_state)
        await h._handle_sequence_key(_key("f"))
        await h._handle_sequence_key(_key("f"))
        assert seen_state == {
            "pending": False,
            "buffer": "",
            "bindings_is_pre": True,
        }

    @pytest.mark.asyncio
    async def test_action_exception_leaves_state_clean(self) -> None:
        h = _make_harness(
            [KeySequence("ff", "filter")],
            groups={"f": "Filter"},
        )
        pre = h._bindings
        h.run_action = AsyncMock(side_effect=RuntimeError("boom"))
        await h._handle_sequence_key(_key("f"))
        with pytest.raises(RuntimeError, match="boom"):
            await h._handle_sequence_key(_key("f"))
        assert h._seq_pending is False
        assert h._seq_buffer == ""
        assert h._bindings is pre


class TestShowContinuations:
    @pytest.mark.asyncio
    async def test_saves_bindings_and_hides_ancestors_on_first_call(self) -> None:
        ancestor = _make_ancestor([Binding("p", "parent", "Parent")])
        h = _make_harness(
            [KeySequence("ff", "filter")],
            groups={"f": "Filter"},
            ancestors=[ancestor],
        )
        original = h._bindings
        original_ancestor = ancestor._bindings
        await h._handle_sequence_key(_key("f"))
        assert h._seq_saved_bindings is original
        assert ancestor._bindings is not original_ancestor
        assert list(ancestor._bindings.key_to_bindings) == []

    @pytest.mark.asyncio
    async def test_continuation_bindings_are_exactly_next_chars_plus_escape(
        self,
    ) -> None:
        h = _make_harness(
            [KeySequence("ff", "filter_ff"), KeySequence("fo", "filter_fo")],
            groups={"f": "Filter"},
        )
        await h._handle_sequence_key(_key("f"))
        assert set(h._bindings.key_to_bindings) == {"f", "o", "escape"}

    @pytest.mark.asyncio
    async def test_shared_next_char_mid_sequence_deduplicates(self) -> None:
        h = _make_harness(
            [KeySequence("ffa", "a"), KeySequence("ffb", "b"), KeySequence("fga", "c")],
            groups={"f": "Filter"},
        )
        await h._handle_sequence_key(_key("f"))
        await h._handle_sequence_key(_key("f"))
        assert set(h._bindings.key_to_bindings) == {"a", "b", "escape"}
        assert len(h._bindings.key_to_bindings["a"]) == 1

    @pytest.mark.asyncio
    async def test_show_flag_propagated_to_continuation_binding(self) -> None:
        h = _make_harness(
            [KeySequence("ff", "filter", show=False)],
            groups={"f": "Filter"},
        )
        await h._handle_sequence_key(_key("f"))
        [binding] = h._bindings.key_to_bindings["f"]
        assert binding.show is False

    @pytest.mark.asyncio
    async def test_second_show_does_not_re_hide_ancestor(self) -> None:
        ancestor = _make_ancestor([Binding("p", "parent", "Parent")])
        h = _make_harness(
            [KeySequence("gga", "go_a")],
            groups={"g": "Go"},
            ancestors=[ancestor],
        )
        await h._handle_sequence_key(_key("g"))
        hidden_bindings = ancestor._bindings
        first_saved_bindings = h._seq_saved_bindings
        saved_ids = [id(b) for _, b in h._seq_saved_ancestor_bindings]
        await h._handle_sequence_key(_key("g"))
        assert ancestor._bindings is hidden_bindings
        assert h._seq_saved_bindings is first_saved_bindings
        assert [id(b) for _, b in h._seq_saved_ancestor_bindings] == saved_ids


class TestAncestorBindings:
    def test_hide_and_restore_are_symmetric(self) -> None:
        a = _make_ancestor([Binding("a", "act_a", "A")])
        b = _make_ancestor([Binding("b", "act_b", "B")])
        h = _make_harness([KeySequence("ff", "filter")], ancestors=[a, b])
        original_a = a._bindings
        original_b = b._bindings
        pre_keys_a = list(a._bindings.key_to_bindings)
        pre_keys_b = list(b._bindings.key_to_bindings)
        h._hide_ancestor_bindings()
        assert list(a._bindings.key_to_bindings) == []
        assert list(b._bindings.key_to_bindings) == []
        h._restore_ancestor_bindings()
        assert a._bindings is original_a
        assert b._bindings is original_b
        assert list(a._bindings.key_to_bindings) == pre_keys_a
        assert list(b._bindings.key_to_bindings) == pre_keys_b
        assert h._seq_saved_ancestor_bindings == []

    def test_hide_skips_ancestor_without_bindings(self) -> None:
        bare = Mock(spec=[])
        h = _make_harness([KeySequence("ff", "filter")], ancestors=[bare])
        h._hide_ancestor_bindings()
        assert h._seq_saved_ancestor_bindings == []

    def test_hide_skips_self(self) -> None:
        a = _make_ancestor([Binding("a", "act_a", "A")])
        h = _make_harness([KeySequence("ff", "filter")], ancestors=[a])
        h._hide_ancestor_bindings()
        saved_objects = [ancestor for ancestor, _ in h._seq_saved_ancestor_bindings]
        assert saved_objects == [a]


class TestResetSequence:
    @pytest.mark.asyncio
    async def test_restores_bindings_and_clears_state(self) -> None:
        h = _make_harness(
            [KeySequence("ff", "filter")],
            groups={"f": "Filter"},
        )
        pre_bindings = h._bindings
        await h._handle_sequence_key(_key("f"))
        h._reset_sequence()
        assert h._seq_pending is False
        assert h._seq_buffer == ""
        assert h._bindings is pre_bindings
        assert h._seq_saved_bindings is None


class TestSetSequenceKeymap:
    def test_updates_lookup_and_refreshes(self) -> None:
        seq = KeySequence("ff", "filter", id="my_id")
        h = _make_harness([seq], groups={"f": "Filter"})
        h.refresh_bindings.reset_mock()
        h.set_sequence_keymap({"my_id": "gx"})
        assert "gx" in h._seq_lookup
        h.refresh_bindings.assert_called_once()


class TestRebuildSequences:
    def test_idempotent(self) -> None:
        h = _make_harness(
            [KeySequence("ff", "filter")],
            groups={"f": "Filter"},
            seed_bindings=[Binding("x", "other", "Other")],
        )
        h._rebuild_sequences()
        h._rebuild_sequences()
        assert list(h._bindings.key_to_bindings) == ["f", "x"]
        assert len(h._bindings.key_to_bindings["f"]) == 1
        assert h._seq_base_bindings is not None
        assert list(h._seq_base_bindings.key_to_bindings) == ["x"]

    @pytest.mark.asyncio
    async def test_resets_pending_state(self) -> None:
        h = _make_harness(
            [KeySequence("ff", "filter")],
            groups={"f": "Filter"},
        )
        await h._handle_sequence_key(_key("f"))
        assert h._seq_pending is True
        h._rebuild_sequences()
        assert h._seq_pending is False
        assert h._seq_buffer == ""


class TestInvariants:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "second_key",
        ["f", "escape", "z"],
        ids=["complete", "cancel", "unknown_continuation"],
    )
    async def test_bindings_restored_after_sequence_ends(self, second_key: str) -> None:
        h = _make_harness(
            [KeySequence("ff", "filter")],
            groups={"f": "Filter"},
        )
        pre = h._bindings
        await h._handle_sequence_key(_key("f"))
        await h._handle_sequence_key(_key(second_key))
        assert h._bindings is pre


class _SeqPilotWidget(KeySequenceMixin, Static, can_focus=True):
    SEQUENCES: ClassVar[list[KeySequence]] = [
        KeySequence("ff", "do_ff", "ff"),
        KeySequence("zap", "do_zap", "zap"),
    ]
    SEQUENCE_GROUPS: ClassVar[dict[str, str]] = {"f": "Filter", "z": "Zap"}

    def __init__(self) -> None:
        super().__init__()
        self.called: list[str] = []

    async def on_key(self, event: Key) -> None:
        if await self._handle_sequence_key(event):
            return

    def action_do_ff(self) -> None:
        self.called.append("ff")

    def action_do_zap(self) -> None:
        self.called.append("zap")


class _SeqPilotApp(App[None]):
    @override
    def compose(self) -> ComposeResult:
        yield _SeqPilotWidget()


class TestPilotIntegration:
    @pytest.mark.asyncio
    async def test_two_char_sequence_round_trip(self) -> None:
        app = _SeqPilotApp()
        async with app.run_test(size=(40, 10)) as pilot:
            widget = app.query_one(_SeqPilotWidget)
            widget.focus()
            await pilot.press("f", "f")
            await pilot.pause()
            assert widget.called == ["ff"]

    @pytest.mark.asyncio
    async def test_three_char_sequence_round_trip(self) -> None:
        app = _SeqPilotApp()
        async with app.run_test(size=(40, 10)) as pilot:
            widget = app.query_one(_SeqPilotWidget)
            widget.focus()
            await pilot.press("z", "a", "p")
            await pilot.pause()
            assert widget.called == ["zap"]

    @pytest.mark.asyncio
    async def test_escape_cancels_without_action(self) -> None:
        app = _SeqPilotApp()
        async with app.run_test(size=(40, 10)) as pilot:
            widget = app.query_one(_SeqPilotWidget)
            widget.focus()
            await pilot.press("f", "escape")
            await pilot.pause()
            assert widget.called == []

    @pytest.mark.asyncio
    async def test_ancestor_app_binding_is_suppressed_during_sequence(self) -> None:
        class _App(App[None]):
            BINDINGS: ClassVar[list[Any]] = [Binding("p", "app_p", "App P")]
            called: list[str]

            def __init__(self) -> None:
                super().__init__()
                self.called = []

            @override
            def compose(self) -> ComposeResult:
                yield _SeqPilotWidget()

            def action_app_p(self) -> None:
                self.called.append("app_p")

        app = _App()
        async with app.run_test(size=(40, 10)) as pilot:
            widget = app.query_one(_SeqPilotWidget)
            widget.focus()
            await pilot.press("f", "p")
            await pilot.pause()
            assert app.called == []
            assert widget.called == []
