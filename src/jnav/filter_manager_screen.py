from typing import override

from textual import on
from textual.app import ComposeResult
from textual.widgets import Static

from jnav.filter_provider import FilterProvider
from jnav.filter_tree import FilterTree
from jnav.filtering import build_expression
from jnav.modal import Modal


class FilterManagerScreen(Modal):
    DEFAULT_CSS = """
    #filter-expression {
        color: $accent;
        background: transparent;
        border: round $background-lighten-2;
        margin: 1 0 0 0;
        padding: 0 1;
        height: auto;
        max-height: 5;
    }
    #filter-expression.empty {
        color: $text-muted;
    }
    #filter-hints {
        color: $text-muted;
        margin: 1 0 0 0;
    }
    """

    modal_title = "Filters"
    modal_width = 70
    footer_columns = 4

    def __init__(self, filter_provider: FilterProvider) -> None:
        super().__init__()
        self._fp = filter_provider

    @override
    def compose_body(self) -> ComposeResult:
        yield FilterTree(self._fp, id="filter-tree")
        yield Static(id="filter-expression")

    @override
    def on_mount(self) -> None:
        self.query_one("#filter-tree", FilterTree).focus()
        self._update_preview()

    @on(FilterTree.Changed)
    def _refresh_preview(self) -> None:
        self._update_preview()

    def _update_preview(self) -> None:
        expr_widget = self.query_one("#filter-expression", Static)
        expr = build_expression(self._fp.root)
        if expr:
            expr_widget.update(f"{expr}")
            expr_widget.remove_class("empty")
        else:
            expr_widget.update("(no active filters)")
            expr_widget.add_class("empty")
