from __future__ import annotations

from bisect import bisect_left
from typing import TYPE_CHECKING, override

from rich.console import RenderableType
from rich.style import Style
from textual.binding import Binding

from .field_manager import FieldManager
from .log_entry_item import LEVEL_COMPONENTS
from .log_entry_renderer import EntryStyles, LogEntryRenderer
from .log_model import LogModel
from .search_engine import SearchEngine
from .store import IndexedEntry
from .virtual_list_view import VirtualListView

if TYPE_CHECKING:
    from textual import getters
    from textual.app import App


class LogListView(VirtualListView[IndexedEntry]):
    if TYPE_CHECKING:
        app = getters.app(App[None])

    COMPONENT_CLASSES = {
        "summary--level-error",
        "summary--level-warning",
        "summary--level-info",
        "summary--level-debug",
        "summary--text",
        "summary--search-highlight",
        "summary--cursor",
        "tree--key",
        "tree--key-selected",
        "tree--value",
        "tree--value-null",
        "tree--json-string",
        "tree--search-highlight",
        "tree--background",
    }

    BINDINGS = [
        Binding("e", "toggle_expanded", "Expand"),
    ]

    DEFAULT_CSS = """
    LogListView {
        height: 1fr;
        background: $surface;
        & > .summary--level-error { color: $error; text-style: bold; }
        & > .summary--level-warning { color: $warning; text-style: bold; }
        & > .summary--level-info { color: $primary; text-style: bold; }
        & > .summary--level-debug { color: $success; text-style: bold; }
        & > .summary--text { color: $foreground; }
        & > .summary--cursor { background: $primary 30%; }
        & > .tree--background { background: $surface-darken-1; }
    }
    """

    def __init__(
        self,
        *,
        model: LogModel,
        fields: FieldManager,
        search: SearchEngine,
        id: str | None = None,
    ) -> None:
        super().__init__(
            render_item=self._render_entry,
            id=id,
        )
        self._model = model
        self._fields = fields
        self._search = search
        self._expanded_mode: bool = True
        self._renderer = LogEntryRenderer(
            search=search,
            custom_fields=self._fields.custom_fields_set,
        )
        self._entry_styles: EntryStyles | None = None

    def _resolve_styles(self) -> EntryStyles:
        base_bg = self.styles.background
        cursor_color = self.get_component_styles("summary--cursor").background
        blended = base_bg.blend(cursor_color, cursor_color.a)
        return EntryStyles(
            text=self.get_component_rich_style("summary--text", partial=True),
            levels={
                comp: self.get_component_rich_style(comp, partial=True)
                for comp in LEVEL_COMPONENTS.values()
            },
            highlight=self.get_component_rich_style(
                "summary--search-highlight", partial=True
            ),
            cursor_bg=Style(bgcolor=blended.rich_color),
            tree_key=self.get_component_rich_style("tree--key", partial=True),
            tree_key_selected=self.get_component_rich_style(
                "tree--key-selected", partial=True
            ),
            tree_value=self.get_component_rich_style("tree--value", partial=True),
            tree_value_null=self.get_component_rich_style(
                "tree--value-null", partial=True
            ),
            tree_json_string=self.get_component_rich_style(
                "tree--json-string", partial=True
            ),
            tree_search_highlight=self.get_component_rich_style(
                "tree--search-highlight", partial=True
            ),
            tree_bg=self.get_component_styles("tree--background").background,
            cursor_color=cursor_color,
        )

    @override
    def render(self) -> RenderableType:
        self._entry_styles = self._resolve_styles()
        self._renderer.custom_fields = self._fields.custom_fields_set
        return super().render()

    def _render_entry(self, ie: IndexedEntry, index: int) -> RenderableType:
        assert self._entry_styles is not None
        return self._renderer.render(
            ie,
            styles=self._entry_styles,
            is_cursor=index == self.index,
            expanded=self._expanded_mode,
            width=self.size.width,
        )

    async def on_mount(self) -> None:
        await self._model.on_append.subscribe_async(self._on_append)
        await self._model.on_rebuild.subscribe_async(self._on_rebuild)
        await self._fields.on_change.subscribe_async(self._on_fields_or_search_changed)
        await self._search.on_change.subscribe_async(self._on_fields_or_search_changed)

    async def _on_fields_or_search_changed(self, _: None) -> None:
        self.refresh()

    def on_focus(self) -> None:
        if self.parent is not None:
            self.parent.add_class("focused")

    def on_blur(self) -> None:
        if self.parent is not None:
            self.parent.remove_class("focused")

    def set_expanded_mode(self, expanded: bool) -> None:
        offset = self.cursor_viewport_offset()
        self._expanded_mode = expanded
        self.scroll_to_cursor_offset(offset)
        self.refresh()

    @property
    def expanded_mode(self) -> bool:
        return self._expanded_mode

    def initial_build(self) -> None:
        self._fields.discover(self._model.all())
        self._rebuild()
        if self._items:
            self.index = 0

    def current_index(self) -> int:
        visible = self._model.visible_indices
        if self.index < len(visible):
            return visible[self.index]
        return 0

    def jump_to_index(self, store_idx: int) -> None:
        visible = self._model.visible_indices
        try:
            self.index = visible.index(store_idx)
        except ValueError:
            pass

    async def _on_append(self, new_entries: list[IndexedEntry]) -> None:
        was_empty = self.count() == 0
        was_at_bottom = not was_empty and self.index >= self.count() - 1

        self._fields.discover(new_entries)
        for ie in new_entries:
            self.append(ie)

        if was_at_bottom:
            self.index = self.count() - 1
        elif was_empty and self._items:
            self.index = 0

    async def _on_rebuild(self, _: None) -> None:
        self._rebuild()

    def _rebuild(self) -> None:
        # Store index of currently highlighted entry (from old items, not model)
        store_idx = self._items[self.index].index if self._items else 0

        # Store viewport offset of currently highlighted entry
        offset = self.cursor_viewport_offset()

        # Rebuild list
        self._items.clear()
        for entry in self._model.visible_entries:
            self._items.append(entry)

        if self._items:
            # Find closest entry to previously highlighted store index and highlight it
            self.index = self._closest_list_index(store_idx)

            # Scroll to approximately same viewport offset as before
            self.scroll_to_cursor_offset(offset)

        if self.is_mounted:
            self.refresh()

    def _closest_list_index(self, store_idx: int) -> int:
        if not self._items:
            return 0
        indices = [ie.index for ie in self._items]
        pos = bisect_left(indices, store_idx)

        # store_idx is at or before the first item
        if pos == 0:
            return 0

        # store_idx is after all items
        if pos >= len(indices):
            return len(indices) - 1

        # store_idx falls between two items — pick the closer one
        before = store_idx - indices[pos - 1]
        after = indices[pos] - store_idx
        return pos if after < before else pos - 1

    def action_toggle_expanded(self) -> None:
        self.set_expanded_mode(not self._expanded_mode)
