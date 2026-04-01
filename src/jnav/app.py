import json
import logging
from pathlib import Path
from typing import override

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.theme import Theme
from textual.widgets import Footer, Header, ListView, Static

from jnav.field_manager import FieldManager
from jnav.field_manager_screen import FieldManagerScreen
from jnav.filter_manager_screen import FilterManagerScreen
from jnav.filter_provider import FilterProvider
from jnav.help_screen import HelpScreen
from jnav.log_model import LogModel
from jnav.search_engine import SearchEngine
from jnav.search_input_screen import SearchInputScreen

from .detail_tree import DetailTree
from .filtering import text_search_expr
from .log_entry_item import LogEntryItem
from .log_list_view import LogListView

logger = logging.getLogger(__name__)


class FilterBar(Static):
    pass


class JnavApp(App[None]):
    CSS = """
    * {
        scrollbar-size-vertical: 1;
        scrollbar-color: $surface-lighten-2;
        scrollbar-color-hover: $surface-lighten-3;
        scrollbar-color-active: $foreground-darken-2;
        scrollbar-background: $surface;
        scrollbar-background-hover: $surface;
        border-title-color: $accent;
    }
    ModalScreen {
        background: $background 80%;
    }
    .tree--key { color: $primary; text-style: italic; }
    .tree--key-selected { color: $primary; text-style: bold underline; }
    .tree--value { color: $foreground; }
    .tree--value-null { color: $foreground; text-style: dim italic; }
    .tree--json-string { color: $warning; text-style: italic; }
    .tree--search-highlight { color: $background; background: $accent; }
    .summary--search-highlight { color: $background; background: $accent; }
    #content-area {
        height: 1fr;
    }
    #filter-bar {
        height: 1;
        padding: 0 1;
        color: $text-muted;
        background: $surface;
    }
    #log-panel {
        opacity: 0.75;
    }
    #log-panel:focus-within {
        opacity: 1.0;
    }
    #filter-bar.focused {
        color: $accent;
    }
    #log-list:focus {
        background-tint: transparent;
    }
    #detail-panel {
        width: 40%;
        border: round $surface-lighten-2;
        border-title-align: center;
        background: $surface;
    }
    #detail-panel:focus-within {
        border: round $accent;
    }
    #detail-tree:focus {
        background-tint: transparent;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("slash", "start_search", "Search", key_display="/"),
        Binding("f", "open_filters", "Filter"),
        Binding("c", "open_columns", "Fields"),
        Binding("ctrl+f", "text_filter", "Text filter"),
        Binding("ctrl+s", "text_filter_or", "Text OR"),
        Binding("d", "toggle_detail", "Detail"),
        Binding("r", "reset", "Reset"),
        Binding("y", "copy_entry", "Copy"),
        Binding("h", "focus_list", show=False),
        Binding("l", "focus_detail", show=False),
        Binding("n", "search_next", show=False),
        Binding("N", "search_prev", show=False),
        Binding("space", "toggle_filters_pause", show=False),
        Binding("question_mark", "show_help", "?", key_display="?"),
        Binding("escape", "escape", show=False),
        Binding("enter", "inspect", "Inspect", show=False),
    ]

    def __init__(
        self,
        model: LogModel,
        filter_provider: FilterProvider,
        fields: FieldManager,
        search: SearchEngine,
        state_file: Path | None = None,
    ) -> None:
        super().__init__()
        self.register_theme(Theme(
            name="jnav",
            primary="#0178D4",
            accent="#61AFEF",
            error="#ba3c5b",
            warning="#ffa62b",
            success="#4EBF71",
            dark=True,
        ))
        self.theme = "jnav"
        self._model = model
        self._filter_provider = filter_provider
        self._fields = fields
        self._search = search
        self._search_pos: int = -1
        self._expanded_mode: bool = True
        self._state_file: Path | None = state_file
        self._detail_visible_on_load: bool = False
        self._show_selected_only_on_load: bool = False

    @override
    def compose(self) -> ComposeResult:
        yield Header()
        yield Horizontal(
            Vertical(
                LogListView(
                    model=self._model,
                    fields=self._fields,
                    search=self._search,
                    id="log-list",
                ),
                FilterBar(id="filter-bar"),
                id="log-panel",
            ),
            Vertical(
                DetailTree(
                    "entry",
                    fields=self._fields,
                    filters=self._filter_provider,
                    search=self._search,
                    id="detail-tree",
                ),
                id="detail-panel",
            ),
            id="content-area",
        )
        yield Footer()

    async def on_mount(self) -> None:
        await self._load_state()

        await self._model.on_append.subscribe_async(self._on_entries_changed)
        await self._model.on_rebuild.subscribe_async(self._on_entries_changed)
        await self._search.on_change.subscribe_async(self._on_search_changed)

        lv = self.query_one("#log-list", LogListView)
        lv.set_chrome(self.query_one("#filter-bar", FilterBar))
        lv.set_expanded_mode(self._expanded_mode)
        lv.focus()

        detail_panel = self.query_one("#detail-panel")
        detail_panel.border_title = "Detail"
        detail_panel.display = self._detail_visible_on_load
        detail_tree = self.query_one("#detail-tree", DetailTree)
        detail_tree.show_selected_only = self._show_selected_only_on_load

        self.call_after_refresh(self._initial_build)

    async def _initial_build(self) -> None:
        self.query_one("#log-list", LogListView).initial_build()
        self._update_filter_bar()

    async def _load_state(self) -> None:
        if not self._state_file or not self._state_file.exists():
            return
        try:
            state = json.loads(self._state_file.read_text())
        except json.JSONDecodeError, OSError:
            return
        await self._filter_provider.set_filters(state.get("filters", []))
        await self._fields.set_custom_fields(state.get("custom_fields", []))
        self._expanded_mode = state.get("expanded_mode", False)
        await self._model.set_filtering_enabled(not state.get("filters_paused", False))
        await self._search.set_term(state.get("search_term", ""))
        self._detail_visible_on_load = state.get("detail_visible", False)
        self._show_selected_only_on_load = state.get("show_selected_only", False)

    def _save_state(self) -> None:
        if not self._state_file:
            return
        detail = self.query_one("#detail-tree", DetailTree)
        panel = self.query_one("#detail-panel")
        lv = self.query_one("#log-list", LogListView)
        state = {
            "filters": self._filter_provider.get_filters(),
            "custom_fields": self._fields.custom_fields,
            "expanded_mode": lv.expanded_mode,
            "filters_paused": self._model.filtering_enabled is False,
            "search_term": self._search.term,
            "entry_index": lv.current_index(),
            "detail_visible": panel.display,
            "show_selected_only": detail.show_selected_only,
        }
        try:
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            self._state_file.write_text(json.dumps(state))
        except OSError:
            pass

    async def _on_entries_changed(self, _: object) -> None:
        self._update_filter_bar()

    async def _on_search_changed(self, _: None) -> None:
        self._search_pos = -1
        self._update_filter_bar()

    def _update_filter_bar(self) -> None:
        bar = self.query_one("#filter-bar", FilterBar)
        total = self._model.count()
        shown = len(self._model.visible_indices)
        n_filters = sum(1 for f in self._filter_provider.get_filters() if f["enabled"])
        n_cols = sum(1 for c in self._fields.custom_fields if c["enabled"])

        n_or = sum(
            1
            for f in self._filter_provider.get_filters()
            if f["enabled"] and f.get("combine") == "or"
        )

        parts: list[str] = [f"Showing {shown}/{total}"]
        if n_filters:
            filter_text = f"{n_filters} filter{'s' if n_filters != 1 else ''}"
            if n_or:
                filter_text += f" ({n_or} OR)"
            if not self._model.filtering_enabled:
                filter_text += " PAUSED"
            parts.append(filter_text)
        if n_cols:
            parts.append(f"{n_cols} field{'s' if n_cols != 1 else ''}")
        if self._search.term:
            total = len(self._search.matches)
            pos = self._search_pos + 1 if total else 0
            parts.append(f"/{self._search.term} ({pos}/{total})")

        bar.update("  \u2502  ".join(parts))

    @override
    async def action_quit(self) -> None:
        self._save_state()
        self.workers.cancel_all()
        self.exit()

    def _focus_main(self) -> None:
        self.query_one("#log-list", LogListView).focus()

    def action_open_filters(self) -> None:
        self.push_screen(FilterManagerScreen(self._filter_provider))

    def action_open_columns(self) -> None:
        self.push_screen(FieldManagerScreen(self._fields))

    def action_start_search(self) -> None:
        async def on_dismiss(term: str | None) -> None:
            if not term:
                return
            await self._search.set_term(term)
            if self._search.matches:
                self._search_pos = 0
                self.query_one("#log-list", LogListView).jump_to_index(
                    self._search.matches[0]
                )
            else:
                self.notify("No matches found", timeout=2)

        self.push_screen(SearchInputScreen(), on_dismiss)

    def action_search_next(self) -> None:
        if not self._search.matches:
            return
        lv = self.query_one("#log-list", LogListView)
        current = lv.current_index()
        for i, store_idx in enumerate(self._search.matches):
            if store_idx > current:
                self._search_pos = i
                lv.jump_to_index(store_idx)
                self._update_filter_bar()
                return
        self.notify("No more matches", timeout=1)

    def action_search_prev(self) -> None:
        if not self._search.matches:
            return
        lv = self.query_one("#log-list", LogListView)
        current = lv.current_index()
        for i in range(len(self._search.matches) - 1, -1, -1):
            if self._search.matches[i] < current:
                self._search_pos = i
                lv.jump_to_index(self._search.matches[i])
                self._update_filter_bar()
                return
        self.notify("No more matches", timeout=1)

    def action_text_filter(self) -> None:
        async def on_dismiss(term: str | None) -> None:
            if term:
                expr = text_search_expr(term)
                await self._filter_provider.add_filter(expr, label=f"text: {term}")

        self.push_screen(SearchInputScreen("Text Filter (AND)"), on_dismiss)

    def action_text_filter_or(self) -> None:
        async def on_dismiss(term: str | None) -> None:
            if term:
                expr = text_search_expr(term)
                await self._filter_provider.add_filter(
                    expr, label=f"text: {term}", combine="or"
                )

        self.push_screen(SearchInputScreen("Text Filter (OR)"), on_dismiss)

    def action_toggle_detail(self) -> None:
        panel = self.query_one("#detail-panel")
        if panel.display:
            panel.display = False
            self._focus_main()
        else:
            panel.display = True

    def action_inspect(self) -> None:
        lv = self.query_one("#log-list", LogListView)
        if self.focused != lv:
            return
        panel = self.query_one("#detail-panel")
        if not panel.display:
            panel.display = True
        self.query_one("#detail-tree", DetailTree).focus()

    async def action_reset(self) -> None:
        await self._fields.clear_custom_fields()
        await self._search.clear()
        await self._filter_provider.clear_filters()
        self.notify("Filters and fields cleared", timeout=2)

    def action_copy_entry(self) -> None:
        tree = self.query_one("#detail-tree", DetailTree)
        if tree.entry:
            text = json.dumps(tree.entry.raw, indent=2, default=str)
            self.copy_to_clipboard(text)
            self.notify("Entry copied to clipboard", timeout=2)

    def action_focus_list(self) -> None:
        if self.query_one("#detail-panel").display:
            self.query_one("#log-list", LogListView).focus()

    def action_focus_detail(self) -> None:
        if self.query_one("#detail-panel").display:
            self.query_one("#detail-tree", DetailTree).focus()

    async def action_toggle_filters_pause(self) -> None:
        if not self._filter_provider.get_filters():
            return
        await self._model.set_filtering_enabled(not self._model.filtering_enabled)
        state = "active" if self._model.filtering_enabled else "paused"
        self.notify(f"Filters {state}", timeout=2)

    def action_show_help(self) -> None:
        self.push_screen(HelpScreen())

    async def action_escape(self) -> None:
        tree = self.query_one("#detail-tree", DetailTree)
        if self.focused == tree:
            self._focus_main()
        elif self._search.active:
            await self._search.clear()

    @on(ListView.Highlighted, "#log-list")
    def on_log_highlighted(self, event: ListView.Highlighted) -> None:
        if event.item and isinstance(event.item, LogEntryItem):
            self.query_one("#detail-tree", DetailTree).show_entry(
                self._model.get(event.item.entry_index), event.item.entry_index
            )

    @on(ListView.Selected, "#log-list")
    def on_log_selected(self, event: ListView.Selected) -> None:
        del event  # unused
        self.action_inspect()
