from typing import override

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from jnav.field_manager import FieldManager
from jnav.manager_screen_common import list_option_prompt


class FieldManagerScreen(ModalScreen[bool]):
    DEFAULT_CSS = """
    FieldManagerScreen {
        align: center middle;
    }
    #field-modal {
        width: 60;
        max-width: 90%;
        height: auto;
        max-height: 70%;
        border: solid $surface-lighten-2;
        background: $surface;
        padding: 1 2;
    }
    #field-modal-title {
        text-style: bold;
        padding: 0 0 1 0;
    }
    #field-list {
        height: auto;
        max-height: 14;
        border: none;
    }
    #field-add-input {
        margin: 1 0 0 0;
    }
    #field-add-input.hidden {
        display: none;
    }
    #field-hints {
        color: $text-muted;
        margin: 1 0 0 0;
    }
    """

    BINDINGS = [
        Binding("escape", "maybe_close", "Close", priority=True),
        Binding("a", "add_mode", "Add", show=False),
        Binding("e", "edit_mode", "Edit", show=False),
        Binding("d", "delete", "Delete", show=False),
        Binding("space", "toggle_item", "Toggle", show=False),
    ]

    def __init__(self, field_manager: FieldManager) -> None:
        super().__init__()
        self._fm = field_manager
        self._editing_idx: int | None = None

    @override
    def compose(self) -> ComposeResult:
        yield Vertical(
            Static("Fields", id="field-modal-title"),
            OptionList(id="field-list"),
            Input(
                placeholder="field path (e.g. data.role)...",
                id="field-add-input",
                classes="hidden",
            ),
            Static(
                "[b]a[/b]:Add  [b]e[/b]:Edit  [b]space[/b]:Toggle  [b]d[/b]:Delete  [b]esc[/b]:Close",
                id="field-hints",
            ),
            id="field-modal",
        )

    def on_mount(self) -> None:
        self._refresh_list()
        self.query_one("#field-list", OptionList).focus()

    def _refresh_list(self, highlight: int | None = None) -> None:
        fields = self._fm.custom_fields
        ol = self.query_one("#field-list", OptionList)
        ol.clear_options()
        if not fields:
            ol.add_option(
                Option(Text(" (no fields selected)", style="dim"), disabled=True)
            )
        else:
            for f in fields:
                ol.add_option(list_option_prompt(f["path"], f["enabled"]))
        if highlight is not None and fields:
            ol.highlighted = min(highlight, len(fields) - 1)

    async def action_toggle_item(self) -> None:
        ol = self.query_one("#field-list", OptionList)
        idx = ol.highlighted
        if idx is not None and idx < len(self._fm.custom_fields):
            await self._fm.toggle_field(idx)
            self._refresh_list(idx)

    async def action_delete(self) -> None:
        ol = self.query_one("#field-list", OptionList)
        idx = ol.highlighted
        if idx is not None and idx < len(self._fm.custom_fields):
            await self._fm.remove_field(idx)
            self._refresh_list(idx)

    def action_add_mode(self) -> None:
        self._editing_idx = None
        inp = self.query_one("#field-add-input", Input)
        inp.remove_class("hidden")
        inp.value = ""
        inp.focus()

    def action_edit_mode(self) -> None:
        ol = self.query_one("#field-list", OptionList)
        idx = ol.highlighted
        fields = self._fm.custom_fields
        if idx is None or idx >= len(fields):
            return
        self._editing_idx = idx
        inp = self.query_one("#field-add-input", Input)
        inp.remove_class("hidden")
        inp.value = fields[idx]["path"]
        inp.focus()

    @on(Input.Submitted, "#field-add-input")
    async def on_add_submitted(self, event: Input.Submitted) -> None:
        raw = event.value.strip().lstrip(".")
        if raw:
            if self._editing_idx is not None:
                await self._fm.edit_field(self._editing_idx, raw)
                highlight = self._editing_idx
            else:
                await self._fm.add_field(raw)
                highlight = len(self._fm.custom_fields) - 1
        else:
            highlight = self._editing_idx
        self._editing_idx = None
        event.input.value = ""
        self.query_one("#field-add-input").add_class("hidden")
        self._refresh_list(highlight)
        self.query_one("#field-list", OptionList).focus()

    def action_maybe_close(self) -> None:
        inp = self.query_one("#field-add-input", Input)
        if not inp.has_class("hidden"):
            self._editing_idx = None
            inp.add_class("hidden")
            inp.value = ""
            self.query_one("#field-list", OptionList).focus()
        else:
            self.dismiss(True)
