from typing import ClassVar, override

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.screen import ModalScreen
from textual.widgets import Input


class TextInputScreen(ModalScreen[str | None]):
    DEFAULT_CSS = """
    TextInputScreen {
        align: center middle;
    }
    #text-input {
        width: 50;
        max-width: 90%;
        height: 3;
        border: round $primary;
        background: $background;
        padding: 0 2;
        margin: 0;

        &:focus {
            background-tint: transparent;
        }
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "close", "Close", priority=True),
        Binding("ctrl+c", "close", show=False),
    ]

    def __init__(
        self,
        title: str = "Search",
        placeholder: str = "search term...",
        initial_value: str = "",
    ) -> None:
        super().__init__()
        self._title = title
        self._placeholder = placeholder
        self._initial_value = initial_value

    @override
    def compose(self) -> ComposeResult:
        yield Input(placeholder=self._placeholder, id="text-input")

    def on_mount(self) -> None:
        self.query_one("#text-input").border_title = self._title
        inp = self.query_one("#text-input", Input)
        if self._initial_value:
            inp.value = self._initial_value
        inp.focus()

    @on(Input.Submitted, "#text-input")
    def on_submitted(self, event: Input.Submitted) -> None:
        term = event.value.strip()
        self.dismiss(term if term else None)

    def action_close(self) -> None:
        self.dismiss(None)
