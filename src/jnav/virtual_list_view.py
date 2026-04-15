from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any, Literal, override

from rich.console import RenderableType
from textual import getters
from textual.app import App
from textual.binding import Binding
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget

from jnav.model import Model

from .offset_group import OffsetGroup
from .scrollbar_overlay import ScrollbarOverlay

type RenderItemFn[T] = Callable[[T, int], RenderableType]


class VirtualListView[T](Widget, can_focus=True):
    """A virtualized list that renders only visible items.

    Instead of creating a widget per item (like Textual's ListView), this widget
    calls a `render_item` callback to produce Rich renderables for each visible item.
    Supports variable-height items, keyboard/mouse scrolling, and a scrollbar overlay.

    Args:
        render_item: Callback ``(item, index) -> RenderableType`` to render each item.
        id: Optional widget ID.
    """

    class Highlighted(Message):
        """Posted when the cursor moves to a new item."""

        def __init__(
            self,
            virtual_list: VirtualListView[Any],
            index: int,
            item: object,
        ) -> None:
            super().__init__()
            self.virtual_list = virtual_list
            self.index = index
            self.item = item

        @property
        @override
        def control(self) -> VirtualListView[Any]:
            return self.virtual_list

    class Selected(Message):
        """Posted when the user presses Enter on the current item."""

        def __init__(
            self,
            virtual_list: VirtualListView[Any],
            index: int,
            item: object,
        ) -> None:
            super().__init__()
            self.virtual_list = virtual_list
            self.index = index
            self.item = item

        @property
        @override
        def control(self) -> VirtualListView[Any]:
            return self.virtual_list

    COMPONENT_CLASSES = {
        "scrollbar--thumb",
    }

    DEFAULT_CSS = """
    VirtualListView {
        & > .scrollbar--thumb { color: $surface-lighten-2; }
    }
    """

    BINDINGS = [
        Binding("j", "cursor_down", show=False),
        Binding("k", "cursor_up", show=False),
        Binding("ctrl+d", "scroll_half_down", show=False),
        Binding("ctrl+u", "scroll_half_up", show=False),
        Binding("G", "jump_bottom", show=False),
        Binding("enter", "select"),
    ]

    index: reactive[int] = reactive(-1, always_update=True)

    _model: Model[T]
    _render_item: RenderItemFn[T]
    _follow: bool

    if TYPE_CHECKING:
        app = getters.app(App[None])

    def __init__(
        self,
        *,
        model: Model[T],
        render_item: RenderItemFn[T],
        id: str | None = None,
        follow: bool = False,
    ) -> None:
        super().__init__(id=id)
        self._model = model
        self._scroll_top_index: int = 0
        self._scroll_line_offset: int = 0
        self._render_item = render_item
        self._follow = follow

    @property
    def scroll_top_index(self) -> int:
        return self._scroll_top_index

    @property
    def scroll_line_offset(self) -> int:
        return self._scroll_line_offset

    def validate_index(self, value: int) -> int:
        if self._model.is_empty():
            return 0
        return max(0, min(value, self._model.count() - 1))

    def watch_index(self, value: int) -> None:
        self._ensure_cursor_visible()
        self.refresh()
        if not self._model.is_empty():
            self.post_message(self.Highlighted(self, value, self._model.get(value)))

    def cursor_down(self) -> None:
        """Move the cursor down by one item."""
        if self.index < self._model.count() - 1:
            self.index += 1

    def cursor_up(self) -> None:
        """Move the cursor up by one item."""
        if self.index > 0:
            self.index -= 1

    def cursor_viewport_offset(self) -> int:
        """Return the cursor's vertical offset from the top of the viewport, in lines.

        Pair with ``scroll_to_cursor_offset`` to save and restore the cursor's
        visual position across content changes.
        """
        offset = -self._scroll_line_offset
        for i in range(self._scroll_top_index, self.index):
            offset += self._render_and_measure(i)
        return offset

    def scroll_to_cursor_offset(self, target_offset: int) -> None:
        """Scroll the viewport so the cursor is at ``target_offset`` lines from the top.

        Walks backward from the cursor, accumulating item heights, to find which
        item should be at the top of the viewport and how far into it to offset.
        """
        lines = 0
        i = self.index
        while i > 0:
            i -= 1
            h = self._render_and_measure(i)
            if lines + h > target_offset:
                new_top = i
                new_offset = h - (target_offset - lines)
                if new_offset >= h:
                    new_top += 1
                    new_offset = 0
                self._scroll_top_index = new_top
                self._scroll_line_offset = new_offset
                return
            lines += h
        self._scroll_top_index = 0
        self._scroll_line_offset = 0

    def _move_cursor_half_page(self, direction: Literal["up", "down"]) -> None:
        half = max(1, self.size.height // 2)
        step = 1 if direction == "down" else -1
        stop = self._model.count() if step == 1 else -1
        lines = 0
        target = self.index
        for i in range(self.index + step, stop, step):
            lines += self._render_and_measure(i)
            target = i
            if lines >= half:
                break
        self.index = target

    def scroll_half_down(self) -> None:
        """Move the cursor down by roughly half a viewport height."""
        self._move_cursor_half_page("down")

    def scroll_half_up(self) -> None:
        """Move the cursor up by roughly half a viewport height."""
        self._move_cursor_half_page("up")

    @property
    def follow(self) -> bool:
        return self._follow

    def action_cursor_down(self) -> None:
        self._follow = False
        self.cursor_down()

    def action_cursor_up(self) -> None:
        self._follow = False
        self.cursor_up()

    def action_scroll_half_down(self) -> None:
        self._follow = False
        self.scroll_half_down()

    def action_scroll_half_up(self) -> None:
        self._follow = False
        self.scroll_half_up()

    def action_jump_top(self) -> None:
        self._follow = False
        self.index = 0

    def action_jump_bottom(self) -> None:
        self._follow = True
        if self.count() > 0:
            self.index = self.count() - 1

    def _scroll_viewport_up(self) -> None:
        self._scroll_line_offset -= 1

        # Still within the current top item, just refresh
        if self._scroll_line_offset >= 0:
            self.refresh()
            return

        # No item above, stay at the top
        if self._scroll_top_index == 0:
            self._scroll_line_offset = 0
            return

        # Move to the item above
        self._scroll_top_index -= 1
        height = self._render_and_measure(self._scroll_top_index)
        self._scroll_line_offset = height - 1

        self.refresh()

    def _scroll_viewport_down(self) -> None:

        # if the number of items below the current top is greater or equal the height of the widget, we can just scroll down without measuring
        remaining_items = self.count() - self._scroll_top_index
        can_scroll = remaining_items > self.size.height

        if not can_scroll:
            # we need to measure the remaining items to see if we have enough content to scroll
            height = 0
            for i in range(self._scroll_top_index, self.count()):
                height += self._render_and_measure(i)
            can_scroll = height > self.size.height

        if not can_scroll:
            return

        self._scroll_line_offset += 1

        height = self._render_and_measure(self._scroll_top_index)

        # End of the current item, move to the next one
        if self._scroll_line_offset == height:
            self._scroll_top_index += 1
            self._scroll_line_offset = 0

        self.refresh()

    def on_mouse_scroll_down(self) -> None:
        self._follow = False
        self._scroll_viewport_down()

    def on_mouse_scroll_up(self) -> None:
        self._follow = False
        self._scroll_viewport_up()

    def action_select(self) -> None:
        if not self._model.is_empty():
            msg = self.Selected(self, self.index, self._model.get(self.index))
            self.post_message(msg)

    def _render_and_measure(self, index: int) -> int:
        renderable = self._render_item(self._model.get(index), index)
        return self._measure_height(renderable)

    def _ensure_cursor_visible(self) -> None:
        if self._model.is_empty() or not self.size.height:
            return
        if self.index < self._scroll_top_index:
            self._scroll_top_index = self.index
            self._scroll_line_offset = 0
            return
        lines = 0
        i = self.index
        while i >= 0:
            h = self._render_and_measure(i)
            if lines + h > self.size.height:
                new_top = i
                new_offset = lines + h - self.size.height
                if new_offset >= h:
                    new_top += 1
                    new_offset = 0
                if new_top > self._scroll_top_index or (
                    new_top == self._scroll_top_index
                    and new_offset > self._scroll_line_offset
                ):
                    self._scroll_top_index = new_top
                    self._scroll_line_offset = new_offset
                return
            lines += h
            i -= 1

    @override
    def watch_has_focus(self, _has_focus: bool) -> None:
        self.app.stylesheet.update_nodes([self], animate=True)

    async def on_mount(self) -> None:
        if self.index < 0 and not self._model.is_empty():
            self.index = 0
        await self._model.on_append.subscribe_async(self._on_model_append)

    async def _on_model_append(self, _: Sequence[T]) -> None:
        if self._follow:
            self.index = self.count() - 1
        elif self.index < 0 and not self._model.is_empty():
            self.index = 0
        self.refresh()

    def count(self) -> int:
        """Return the total number of items."""
        return self._model.count()

    def scroll_to_item(self, index: int) -> None:
        """Scroll the viewport so that the item at ``index`` is at the top."""
        if index < 0 or index >= self._model.count():
            raise IndexError("Item index out of range")
        self._scroll_top_index = index
        self._scroll_line_offset = 0
        self.refresh()

    @override
    def render(self) -> RenderableType:
        if self._model.is_empty():
            return ""
        height = self.size.height
        renderables: list[RenderableType] = []
        lines_used = -self._scroll_line_offset
        last_rendered = self._scroll_top_index
        for i in range(self._scroll_top_index, self._model.count()):
            item = self._model.get(i)
            renderable = self._render_item(item, i)
            item_height = self._measure_height(renderable)
            renderables.append(renderable)
            last_rendered = i
            lines_used += item_height
            if lines_used >= height:
                break

        inner: RenderableType = OffsetGroup(renderables, self._scroll_line_offset)

        return ScrollbarOverlay(
            inner,
            total_items=self._model.count(),
            visible_count=last_rendered - self._scroll_top_index + 1,
            scroll_position=self._scroll_top_index,
            thumb_style=self.get_component_rich_style(
                "scrollbar--thumb",
                partial=True,
            ),
        )

    def _measure_height(self, renderable: RenderableType) -> int:
        console = self.app.console
        options = console.options.update_width(self.size.width)
        lines = 0
        for segment in console.render(renderable, options):
            lines += segment.text.count("\n")
        return max(lines, 1)
