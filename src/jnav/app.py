import logging
from typing import ClassVar, override

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal
from textual.theme import Theme
from textual.widgets import Footer

from jnav.detail_panel import DetailPanel
from jnav.filter_manager_screen import FilterManagerScreen
from jnav.filter_provider import FilterProvider
from jnav.header import Header
from jnav.help_screen import HelpScreen
from jnav.log_list_panel import LogListPanel
from jnav.log_model import LogModel
from jnav.role_mapper import RoleMapper
from jnav.search_engine import SearchEngine
from jnav.selector_manager_screen import SelectorManagerScreen
from jnav.selector_provider import SelectorProvider
from jnav.state import AppState

logger = logging.getLogger(__name__)


class JnavApp(App[AppState]):
    ENABLE_COMMAND_PALETTE = False

    DEFAULT_CSS = """
    * {
        scrollbar-size-vertical: 1;
        scrollbar-color: $surface-lighten-2;
        scrollbar-color-hover: $surface-lighten-3;
        scrollbar-color-active: $foreground-darken-2;
        scrollbar-background: $surface;
        scrollbar-background-hover: $surface;
        border-title-color: $primary;
    }
    ModalScreen {
        background: $background 0%;
    }
    JnavApp {
        Footer { background: $surface; }
        FooterKey {
            margin: 0 1 0 0;
            .footer-key--key { color: $primary; }
        }
    }
    .tree--key { color: $primary; text-style: italic; }
    .tree--key-selected { color: $primary; text-style: bold; }
    .tree--value { color: $foreground; }
    .tree--value-null { color: $foreground; text-style: dim italic; }
    .tree--json-string { color: $warning; text-style: italic; }
    .tree--search-highlight { color: $background; background: $accent; }
    #content-area {
        height: 1fr;
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("F", "open_filters", "Filters ≡"),
        Binding("S", "open_columns", "Selectors ≡"),
        Binding("d", "toggle_detail", "Toggle Detail"),
        Binding("r", "reset", "Reset"),
        Binding("question_mark", "show_help", "Help", key_display="?"),
        Binding("q", "quit", "Quit", show=False),
        Binding("h", "focus_list", show=False),
        Binding("l", "focus_detail", show=False),
    ]

    def __init__(
        self,
        *,
        model: LogModel,
        filter_provider: FilterProvider,
        role_mapper: RoleMapper,
        selectors: SelectorProvider,
        search: SearchEngine,
        file_name: str,
        expanded_mode: bool = True,
        detail_visible: bool = False,
        show_selected_only: bool = False,
        collapsed_paths: set[str] | None = None,
        follow: bool = False,
    ) -> None:
        super().__init__()
        self.register_theme(
            Theme(
                name="jnav",
                primary="#339af0",
                accent="#20c997",
                error="#ff6b6b",
                warning="#ff922b",
                success="#20c997",
                surface="#15191d",
                background="#212529",
                foreground="#f8fafb",
                dark=True,
            )
        )
        self.theme = "jnav"
        self._model = model
        self._filter_provider = filter_provider
        self._role_mapper = role_mapper
        self._selectors = selectors
        self._search = search
        self._expanded_mode = expanded_mode
        self._detail_visible = detail_visible
        self._show_selected_only = show_selected_only
        self._collapsed_paths = collapsed_paths
        self._start_following = follow
        self._file_name = file_name
        self.sub_title = file_name

    @override
    def compose(self) -> ComposeResult:
        yield Header(self._file_name)
        yield Horizontal(
            LogListPanel(
                model=self._model,
                selectors=self._selectors,
                filter_provider=self._filter_provider,
                search=self._search,
                role_mapper=self._role_mapper,
                start_following=self._start_following,
                expanded_mode=self._expanded_mode,
            ),
            DetailPanel(
                selectors=self._selectors,
                filter_provider=self._filter_provider,
                search=self._search,
                role_mapper=self._role_mapper,
                visible=self._detail_visible,
                show_selected_only=self._show_selected_only,
                collapsed_paths=self._collapsed_paths,
            ),
            id="content-area",
        )
        yield Footer()

    def to_state(self) -> AppState:
        detail = self.query_one(DetailPanel)
        log_list = self.query_one(LogListPanel)
        return AppState(
            filter_root=self._filter_provider.root,
            selectors=self._selectors.selectors,
            role_mapping=self._role_mapper.mapping,
            search_term=self._search.term,
            filtering_enabled=self._model.filtering_enabled,
            expanded_mode=log_list.expanded_mode,
            detail_visible=bool(detail.display),
            show_selected_only=detail.show_selected_only,
            entry_index=log_list.current_index(),
            collapsed_paths=detail.collapsed_paths,
        )

    @override
    async def action_quit(self) -> None:
        state = self.to_state()
        self.workers.cancel_all()
        self.exit(state)

    def action_open_filters(self) -> None:
        self.push_screen(FilterManagerScreen(self._filter_provider))

    def action_open_columns(self) -> None:
        self.push_screen(SelectorManagerScreen(self._selectors))

    def action_toggle_detail(self) -> None:
        panel = self.query_one(DetailPanel)
        if panel.display:
            self.query_one(LogListPanel).focus()
        panel.display = not panel.display

    async def action_reset(self) -> None:
        await self._selectors.clear_selectors()
        await self._search.clear()
        await self._filter_provider.clear_filters()
        self.notify("Filters and fields cleared", timeout=2)

    def action_focus_list(self) -> None:
        self.query_one(LogListPanel).focus()

    def action_focus_detail(self) -> None:
        panel = self.query_one(DetailPanel)
        if panel.display:
            panel.focus()

    def action_show_help(self) -> None:
        self.push_screen(HelpScreen())

    @on(DetailPanel.Closed)
    def on_detail_closed(self, event: DetailPanel.Closed) -> None:
        del event  # unused
        self.query_one(LogListPanel).focus()

    @on(LogListPanel.Highlighted)
    def on_log_highlighted(self, event: LogListPanel.Highlighted) -> None:
        ie = event.entry
        self.query_one(DetailPanel).show_entry(ie.entry, ie.index)

    @on(LogListPanel.Selected)
    def on_log_selected(self, event: LogListPanel.Selected) -> None:
        del event  # unused
        panel = self.query_one(DetailPanel)
        panel.display = True
        panel.focus()
