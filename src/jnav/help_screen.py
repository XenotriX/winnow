from typing import override
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static


HELP_TEXT = """\
[b]Global[/b]
  [b]j/k[/b]       Navigate entries (or arrow keys)
  [b]h/l[/b]       Switch focus: list ↔ detail
  [b]Ctrl+D/U[/b]  Half-page scroll down/up
  [b]/[/b]         Search (highlight matches, n/N to navigate)
  [b]n/N[/b]       Next/previous search match
  [b]f[/b]         Manage filters (hide non-matching entries)
  [b]c[/b]         Manage selected fields
  [b]Ctrl+F[/b]    Add text filter (AND)
  [b]Ctrl+S[/b]    Add text filter (OR)
  [b]space[/b]     Pause/unpause filters
  [b]e[/b]         Toggle expanded view
  [b]d[/b]         Toggle detail panel
  [b]r[/b]         Reset all filters, fields, and search
  [b]y[/b]         Copy current entry as JSON
  [b]g[/b]         Jump to first entry
  [b]G[/b]         Jump to last entry
  [b]?[/b]         This help
  [b]q[/b]         Quit

[b]Table / Expanded View[/b]
  [b]Enter[/b]     Open detail panel and inspect entry

[b]Detail Panel[/b]
  [b]f f[/b]       Filter by value (AND)
  [b]f o[/b]       Filter by value (OR)
  [b]f n[/b]       Has field (AND)
  [b]f N[/b]       Has field (OR)
  [b]s[/b]         Select this field for display
  [b]v[/b]         View value in $EDITOR
  [b]t[/b]         Toggle: show only selected fields
  [b]Escape[/b]    Return to main view
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

    BINDINGS = [
        Binding("escape", "close", "Close", priority=True),
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
