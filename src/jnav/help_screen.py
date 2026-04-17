from typing import ClassVar, override

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static

HELP_TEXT = """\
[b]Navigation[/b]
  [b]j/k[/b]       Cursor down/up
  [b]gg/G[/b]      Jump to top/bottom
  [b]Ctrl+D/U[/b]  Half-page down/up
  [b]h/l[/b]       Focus list/detail
  [b]Enter[/b]     Inspect entry
  [b]Escape[/b]    Back

[b]Actions[/b]
  [b]/[/b]         Search
  [b]n/N[/b]       Next/prev match
  [b]F[/b]         Filter manager
  [b]ft[/b]        Text filter
  [b]fp[/b]        Pause/resume filters
  [b]S[/b]         Selected fields manager
  [b]vi[/b]        Toggle inline expanded tree
  [b]d[/b]         Toggle detail panel
  [b]r[/b]         Reset filters, fields, search
  [b]?[/b]         This help
  [b]q[/b]         Quit

[b]Detail Panel[/b]
  [b]ff[/b]        Filter by value
  [b]fn[/b]        Has field
  [b]s[/b]         (Un)select field
  [b]ve[/b]        View value in $EDITOR
  [b]vo[/b]        Show selected fields only
"""


class HelpScreen(ModalScreen[bool]):
    DEFAULT_CSS = """
    HelpScreen {
        align: center middle;
    }
    #help-modal {
        width: 55;
        max-width: 90%;
        height: auto;
        max-height: 80%;
        border: round $surface-lighten-2;
        background: $surface;
        padding: 1 2;
    }
    #help-hints {
        color: $text-muted;
        padding: 1 0 0 0;
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "close", "Close", priority=True),
        Binding("q", "close", show=False),
        Binding("ctrl+c", "close", show=False),
        Binding("question_mark", "close", show=False),
    ]

    @override
    def compose(self) -> ComposeResult:
        yield Vertical(
            Static(HELP_TEXT),
            Static("[b]esc[/b] or [b]?[/b] to close", id="help-hints"),
            id="help-modal",
        )

    def on_mount(self) -> None:
        self.query_one("#help-modal").border_title = "Keybindings"

    def action_close(self) -> None:
        self.dismiss(True)
