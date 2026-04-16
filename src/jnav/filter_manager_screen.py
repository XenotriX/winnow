from typing import ClassVar, override

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static

from jnav.filter_provider import FilterProvider
from jnav.filter_tree import FilterTree
from jnav.filtering import build_expression


class FilterManagerScreen(ModalScreen[bool]):
    DEFAULT_CSS = """
    FilterManagerScreen {
        align: center middle;
    }
    #filter-modal {
        width: 70;
        max-width: 90%;
        height: auto;
        max-height: 70%;
        border: round $primary;
        background: $background;
        padding: 1 2;
    }
    #filter-expression {
        color: $primary;
        background: $surface;
        margin: 1 0 0 0;
        padding: 0 1;
        height: auto;
        max-height: 3;
    }
    #filter-expression.empty {
        color: $text-muted;
    }
    #filter-hints {
        color: $text-muted;
        margin: 1 0 0 0;
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "maybe_close", "Close", priority=True),
        Binding("q", "maybe_close", show=False),
        Binding("ctrl+c", "maybe_close", show=False),
    ]

    def __init__(self, filter_provider: FilterProvider) -> None:
        super().__init__()
        self._fp = filter_provider

    @override
    def compose(self) -> ComposeResult:
        yield Vertical(
            FilterTree(self._fp, id="filter-tree"),
            Static(id="filter-expression"),
            Static(
                "[b]a[/b]:Add  [b]g[/b]:Group  [b]e[/b]:Edit  [b]t[/b]:Toggle  [b]n[/b]:Negate  [b]o[/b]:AND/OR  [b]d[/b]:Cut  [b]p[/b]:Paste  [b]r[/b]:Rename  [b]esc[/b]:Close",
                id="filter-hints",
            ),
            id="filter-modal",
        )

    def on_mount(self) -> None:
        self.query_one("#filter-modal").border_title = "Filters"
        self.query_one("#filter-tree", FilterTree).focus()
        self._update_preview()

    def on_filter_tree_changed(self) -> None:
        self._update_preview()

    def _update_preview(self) -> None:
        expr_widget = self.query_one("#filter-expression", Static)
        expr = build_expression(self._fp.root)
        if expr:
            expr_widget.update(f"jq: {expr}")
            expr_widget.remove_class("empty")
        else:
            expr_widget.update("jq: (no active filters)")
            expr_widget.add_class("empty")

    def action_maybe_close(self) -> None:
        self.dismiss(True)
