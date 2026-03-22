from typing import override
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Static


class SearchInputScreen(ModalScreen[str | None]):
    DEFAULT_CSS = """
    SearchInputScreen {
        align: center middle;
    }
    #search-modal {
        width: 50;
        max-width: 90%;
        height: auto;
        border: solid $surface-lighten-2;
        background: $surface;
        padding: 1 2;
    }
    #search-title {
        text-style: bold;
        padding: 0 0 1 0;
    }
    """

    BINDINGS = [
        Binding("escape", "close", "Close", priority=True),
    ]

    def __init__(
        self, title: str = "Search", placeholder: str = "search term..."
    ) -> None:
        super().__init__()
        self._title = title
        self._placeholder = placeholder

    @override
    def compose(self) -> ComposeResult:
        yield Vertical(
            Static(self._title, id="search-title"),
            Input(placeholder=self._placeholder, id="search-input"),
            id="search-modal",
        )

    def on_mount(self) -> None:
        self.query_one("#search-input", Input).focus()

    @on(Input.Submitted, "#search-input")
    def on_submitted(self, event: Input.Submitted) -> None:
        term = event.value.strip()
        self.dismiss(term if term else None)

    def action_close(self) -> None:
        self.dismiss(None)
