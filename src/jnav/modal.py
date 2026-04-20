from abc import ABC, ABCMeta, abstractmethod
from typing import ClassVar, override

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.screen import ModalScreen

from jnav.manager_screen_common import WrappingFooter


class _ModalMeta(ABCMeta, type(ModalScreen)):
    pass


class Modal(ModalScreen[bool], ABC, metaclass=_ModalMeta):
    DEFAULT_CSS = """
    Modal {
        align: center middle;
    }
    Modal .modal-box {
        max-width: 90%;
        height: auto;
        max-height: 70%;
        border: round $primary;
        background: $background;
    }
    Modal .modal-body {
        padding: 1 2;
        height: auto;
    }
    .modal-box Footer {
        background: transparent;
        layout: grid;
        height: auto;
        dock: initial;
    }
    .modal-box FooterKey .footer-key--key {
        color: $primary;
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "maybe_close", "Close", show=False),
        Binding("q", "maybe_close", show=False),
        Binding("ctrl+c", "maybe_close", show=False),
    ]

    modal_title: ClassVar[str] = ""
    modal_width: ClassVar[int] = 60
    footer_columns: ClassVar[int] = 4

    @override
    def compose(self) -> ComposeResult:
        yield Vertical(
            Vertical(*self.compose_body(), classes="modal-body"),
            WrappingFooter(columns=self.footer_columns),
            classes="modal-box",
        )

    @abstractmethod
    def compose_body(self) -> ComposeResult: ...

    def on_mount(self) -> None:
        box = self.query_one(".modal-box", Vertical)
        box.border_title = self.modal_title
        box.styles.width = self.modal_width

    def action_maybe_close(self) -> None:
        self.dismiss(True)
