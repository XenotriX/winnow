from typing import Literal, TypedDict, override

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from jnav.filtering import Filter, check_filter_warning
from jnav.manager_screen_common import list_option_prompt


class FilterManagerScreen(ModalScreen[bool]):
    filters: list[Filter]
    DEFAULT_CSS = """
    FilterManagerScreen {
        align: center middle;
    }
    #filter-modal {
        width: 70;
        max-width: 90%;
        height: auto;
        max-height: 70%;
        border: solid $surface-lighten-2;
        background: $surface;
        padding: 1 2;
    }
    #filter-modal-title {
        text-style: bold;
        padding: 0 0 1 0;
    }
    #filter-list {
        height: auto;
        max-height: 14;
        border: none;
    }
    #filter-add-input {
        margin: 1 0 0 0;
    }
    #filter-add-input.hidden {
        display: none;
    }
    #filter-hints {
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
        Binding("o", "toggle_combine", "AND/OR", show=False),
    ]

    def __init__(self, filters: list[Filter]) -> None:
        super().__init__()
        self.filters = filters
        self._editing_idx: int | None = None

    @override
    def compose(self) -> ComposeResult:
        yield Vertical(
            Static("Filters", id="filter-modal-title"),
            OptionList(id="filter-list"),
            Input(
                placeholder="jq expression...", id="filter-add-input", classes="hidden"
            ),
            Static(
                "[b]a[/b]:Add  [b]e[/b]:Edit  [b]space[/b]:Toggle  [b]o[/b]:AND/OR  [b]d[/b]:Delete  [b]esc[/b]:Close",
                id="filter-hints",
            ),
            id="filter-modal",
        )

    def on_mount(self) -> None:
        self._refresh_list()
        self.query_one("#filter-list", OptionList).focus()

    def _refresh_list(self, highlight: int | None = None) -> None:
        ol = self.query_one("#filter-list", OptionList)
        ol.clear_options()
        if not self.filters:
            ol.add_option(Option(Text(" (no filters)", style="dim"), disabled=True))
        else:
            for f in self.filters:
                ol.add_option(
                    list_option_prompt(
                        f.get("label") or f["expr"],
                        f["enabled"],
                        f["combine"],
                    )
                )
        if highlight is not None and self.filters:
            ol.highlighted = min(highlight, len(self.filters) - 1)

    def action_toggle_item(self) -> None:
        ol = self.query_one("#filter-list", OptionList)
        idx = ol.highlighted
        if idx is not None and idx < len(self.filters):
            self.filters[idx]["enabled"] = not self.filters[idx]["enabled"]
            self._refresh_list(idx)

    def action_toggle_combine(self) -> None:
        ol = self.query_one("#filter-list", OptionList)
        idx = ol.highlighted
        if idx is not None and idx < len(self.filters):
            current = self.filters[idx].get("combine", "and")
            self.filters[idx]["combine"] = "or" if current == "and" else "and"
            self._refresh_list(idx)

    def action_delete(self) -> None:
        ol = self.query_one("#filter-list", OptionList)
        idx = ol.highlighted
        if idx is not None and idx < len(self.filters):
            self.filters.pop(idx)
            self._refresh_list(idx)

    def action_add_mode(self) -> None:
        self._editing_idx = None
        inp = self.query_one("#filter-add-input", Input)
        inp.remove_class("hidden")
        inp.value = ""
        inp.focus()

    def action_edit_mode(self) -> None:
        ol = self.query_one("#filter-list", OptionList)
        idx = ol.highlighted
        if idx is None or idx >= len(self.filters):
            return
        self._editing_idx = idx
        inp = self.query_one("#filter-add-input", Input)
        inp.remove_class("hidden")
        inp.value = self.filters[idx]["expr"]
        inp.focus()

    @on(Input.Submitted, "#filter-add-input")
    def on_add_submitted(self, event: Input.Submitted) -> None:
        expr = event.value.strip()
        if expr:
            warning = check_filter_warning(expr)
            if self._editing_idx is not None:
                self.filters[self._editing_idx]["expr"] = expr
                self.filters[self._editing_idx].pop("label", None)
                highlight = self._editing_idx
            else:
                self.filters.append({"expr": expr, "enabled": True, "combine": "and"})
                highlight = len(self.filters) - 1
            if warning:
                self.notify(warning, severity="warning", timeout=3)
        else:
            highlight = self._editing_idx
        self._editing_idx = None
        event.input.value = ""
        self.query_one("#filter-add-input").add_class("hidden")
        self._refresh_list(highlight)
        self.query_one("#filter-list", OptionList).focus()

    def action_maybe_close(self) -> None:
        inp = self.query_one("#filter-add-input", Input)
        if not inp.has_class("hidden"):
            self._editing_idx = None
            inp.add_class("hidden")
            inp.value = ""
            self.query_one("#filter-list", OptionList).focus()
        else:
            self.dismiss(True)
