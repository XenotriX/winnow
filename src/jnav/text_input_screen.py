from typing import override
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input


class TextInputScreen(ModalScreen[str | None]):
    DEFAULT_CSS = """
    TextInputScreen {
        align: center middle;
    }
    #text-input-modal {
        width: 50;
        max-width: 90%;
        height: auto;
        border: round $surface-lighten-2;
        background: $surface;
        padding: 1 2;
    }
    """

    BINDINGS = [
        Binding("escape", "close", "Close", priority=True),
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
        yield Vertical(
            Input(placeholder=self._placeholder, id="text-input"),
            id="text-input-modal",
        )

    def on_mount(self) -> None:
        self.query_one("#text-input-modal").border_title = self._title
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
