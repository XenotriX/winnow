from typing import ClassVar, Self, override

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.message import Message

from jnav.detail_tree import DetailTree
from jnav.filter_provider import FilterProvider
from jnav.parsing import ParsedEntry
from jnav.role_mapper import RoleMapper
from jnav.search_engine import SearchEngine
from jnav.selector_provider import SelectorProvider


class DetailPanel(Vertical):
    BORDER_TITLE: ClassVar[str] = "Detail"

    class Closed(Message):
        pass

    DEFAULT_CSS = """
    DetailPanel {
        width: 40%;
        border: round $background-lighten-2;
        border-title-align: center;
        background: $background;
        &.focused { border: round $primary; }
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "close", show=False),
    ]

    def __init__(
        self,
        *,
        selectors: SelectorProvider,
        filter_provider: FilterProvider,
        search: SearchEngine,
        role_mapper: RoleMapper,
        visible: bool = False,
        show_selected_only: bool = False,
        collapsed_paths: set[str] | None = None,
    ) -> None:
        super().__init__()
        self._selectors = selectors
        self._filter_provider = filter_provider
        self._search = search
        self._role_mapper = role_mapper
        self._show_selected_only = show_selected_only
        self._collapsed_paths = collapsed_paths
        self.display = visible

    @override
    def compose(self) -> ComposeResult:
        yield DetailTree(
            "entry",
            selectors=self._selectors,
            filters=self._filter_provider,
            search=self._search,
            role_mapper=self._role_mapper,
            show_selected_only=self._show_selected_only,
            collapsed_paths=self._collapsed_paths,
            id="detail-tree",
        )

    @property
    def collapsed_paths(self) -> set[str]:
        return self._tree.collapsed_paths

    @property
    def _tree(self) -> DetailTree:
        return self.query_one(DetailTree)

    @property
    def show_selected_only(self) -> bool:
        return self._tree.show_selected_only

    def show_entry(self, parsed: ParsedEntry, index: int) -> None:
        self._tree.show_entry(parsed, index)

    @override
    def focus(self, scroll_visible: bool = True) -> Self:
        self._tree.focus(scroll_visible)
        return self

    def action_close(self) -> None:
        self.post_message(self.Closed())
