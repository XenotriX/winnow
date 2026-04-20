from typing import TYPE_CHECKING, ClassVar, override

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.widgets import OptionList
from textual.widgets.option_list import Option

from jnav.manager_screen_common import list_option_prompt
from jnav.modal import Modal
from jnav.selector_provider import SelectorProvider
from jnav.text_input_screen import TextInputScreen

if TYPE_CHECKING:
    from textual import getters
    from textual.app import App


class SelectorManagerScreen(Modal):
    if TYPE_CHECKING:
        app = getters.app(App[None])

    DEFAULT_CSS = """
    #selector-list {
        height: auto;
        max-height: 14;
        border: none;
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("a", "add", "Add"),
        Binding("e", "edit", "Edit"),
        Binding("d", "delete", "Cut"),
        Binding("y", "yank", "Yank"),
        Binding("p", "paste", "Paste"),
        Binding("t", "toggle_item", "Toggle"),
        Binding("j", "cursor_down", show=False),
        Binding("k", "cursor_up", show=False),
    ]

    modal_title = "Selectors"
    modal_width = 60
    footer_columns = 6

    def __init__(self, selector_provider: SelectorProvider) -> None:
        super().__init__()
        self._sp = selector_provider
        self._clipboard: str | None = None

    @override
    def compose_body(self) -> ComposeResult:
        yield OptionList(id="selector-list")

    @override
    def on_mount(self) -> None:
        self._refresh_list(highlight=0)
        self.query_one("#selector-list", OptionList).focus()

    def _refresh_list(self, highlight: int | None = None) -> None:
        selectors = self._sp.selectors
        ol = self.query_one("#selector-list", OptionList)
        ol.clear_options()
        if not selectors:
            ol.add_option(Option(Text(" (no selectors)", style="dim"), disabled=True))
        else:
            for s in selectors:
                ol.add_option(list_option_prompt(s["path"], s["enabled"]))
        if highlight is not None and selectors:
            ol.highlighted = min(highlight, len(selectors) - 1)

    def action_cursor_down(self) -> None:
        self.query_one("#selector-list", OptionList).action_cursor_down()

    def action_cursor_up(self) -> None:
        self.query_one("#selector-list", OptionList).action_cursor_up()

    async def action_toggle_item(self) -> None:
        ol = self.query_one("#selector-list", OptionList)
        idx = ol.highlighted
        if idx is not None and idx < len(self._sp.selectors):
            await self._sp.toggle_selector(idx)
            self._refresh_list(idx)

    async def action_delete(self) -> None:
        ol = self.query_one("#selector-list", OptionList)
        idx = ol.highlighted
        selectors = self._sp.selectors
        if idx is None or idx >= len(selectors):
            return
        self._clipboard = selectors[idx]["path"]
        await self._sp.remove_selector(idx)
        self._refresh_list(idx)

    def action_yank(self) -> None:
        ol = self.query_one("#selector-list", OptionList)
        idx = ol.highlighted
        selectors = self._sp.selectors
        if idx is None or idx >= len(selectors):
            return
        self._clipboard = selectors[idx]["path"]

    async def action_paste(self) -> None:
        if self._clipboard is None:
            return
        ol = self.query_one("#selector-list", OptionList)
        idx = ol.highlighted
        target = (idx + 1) if idx is not None else len(self._sp.selectors)
        await self._sp.insert_selector(target, self._clipboard)
        self._clipboard = None
        self._refresh_list(target)

    def action_add(self) -> None:
        ol = self.query_one("#selector-list", OptionList)
        idx = ol.highlighted
        target = (idx + 1) if idx is not None else len(self._sp.selectors)

        async def on_dismiss(value: str | None) -> None:
            if not value:
                return
            path = value.strip()
            if not path:
                return
            await self._sp.insert_selector(target, path)
            self._refresh_list(target)

        self.app.push_screen(
            TextInputScreen("Add selector", placeholder="jq selector..."),
            on_dismiss,
        )

    def action_edit(self) -> None:
        ol = self.query_one("#selector-list", OptionList)
        idx = ol.highlighted
        selectors = self._sp.selectors
        if idx is None or idx >= len(selectors):
            return
        current = selectors[idx]["path"]

        async def on_dismiss(value: str | None) -> None:
            if not value:
                return
            path = value.strip()
            if not path:
                return
            await self._sp.edit_selector(idx, path)
            self._refresh_list(idx)

        self.app.push_screen(
            TextInputScreen(
                "Edit selector",
                placeholder="jq selector...",
                initial_value=current,
            ),
            on_dismiss,
        )
