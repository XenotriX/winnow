from dataclasses import dataclass
from typing import cast, override

import pytest
from aioreactive import AsyncSubject
from rich.console import RenderableType
from rich.text import Text
from textual.app import App, ComposeResult

from jnav.virtual_list_view import RenderItemFn, VirtualListView


class ListModel[T]:
    """Minimal model stub for VirtualListView tests."""

    def __init__(self, items: list[T] | None = None) -> None:
        self._items: list[T] = list(items or [])
        self.on_append: AsyncSubject[list[T]] = AsyncSubject()

    def count(self) -> int:
        return len(self._items)

    def get(self, pos: int) -> T:
        return self._items[pos]

    def is_empty(self) -> bool:
        return len(self._items) == 0

    def append(self, item: T) -> None:
        self._items.append(item)

    @property
    def visible_indices(self) -> list[int]:
        return list(range(len(self._items)))


def get_visible_items[T](vl: VirtualListView[T]) -> list[T]:
    height = vl.size.height
    result: list[T] = []
    lines_used = -vl.scroll_line_offset
    for i in range(vl.scroll_top_index, vl.count()):
        renderable = vl._render_item(vl._model.get(i), i)  # pyright: ignore[reportPrivateUsage]
        console = vl.app.console
        options = console.options.update_width(vl.size.width)
        lines = 0
        for segment in console.render(renderable, options):
            lines += segment.text.count("\n")
        h = max(lines, 1)
        result.append(vl._model.get(i))  # pyright: ignore[reportPrivateUsage]
        lines_used += h
        if lines_used >= height:
            break
    return result


def render_str(item: str, index: int) -> RenderableType:
    del index  # unused
    return Text(item, no_wrap=True)


class VirtualListApp[T](App[None]):
    def __init__(
        self,
        items: list[T],
        *,
        render_item: RenderItemFn[T] = render_str,  # type: ignore[assignment]
        follow: bool = False,
    ) -> None:
        super().__init__()
        self._items = items
        self._render_item = render_item
        self._follow = follow

    @override
    def compose(self) -> ComposeResult:
        model = ListModel(self._items)
        vl: VirtualListView[T] = VirtualListView(
            model=model,  # type: ignore[arg-type]
            render_item=self._render_item,
            follow=self._follow,
        )
        yield vl


def test_model_backed_count():
    model = ListModel(["a", "b", "c"])
    widget: VirtualListView[str] = VirtualListView(
        model=model,  # type: ignore[arg-type]
        render_item=render_str,
    )
    assert widget.count() == 3


@pytest.mark.asyncio
async def test_visible_items_limited_by_height():
    items = [f"item_{i}" for i in range(100)]
    app = VirtualListApp(items)
    async with app.run_test(size=(80, 24)) as pilot:
        del pilot  # unused
        vl = cast(VirtualListView[str], app.query_one(VirtualListView))
        assert len(get_visible_items(vl)) == 24


@pytest.mark.asyncio
async def test_visible_items_limited_by_item_count():
    items = [f"item_{i}" for i in range(5)]
    app = VirtualListApp(items)
    async with app.run_test(size=(80, 24)) as pilot:
        del pilot  # unused
        vl = cast(VirtualListView[str], app.query_one(VirtualListView))
        assert len(get_visible_items(vl)) == 5


@pytest.mark.asyncio
async def test_visible_items_shows_first_n():
    items = [f"item_{i}" for i in range(100)]
    app = VirtualListApp(items)
    async with app.run_test(size=(80, 10)) as pilot:
        del pilot  # unused
        vl = cast(VirtualListView[str], app.query_one(VirtualListView))
        visible = get_visible_items(vl)
        assert visible == [f"item_{i}" for i in range(10)]


@pytest.mark.asyncio
async def test_append_to_model_after_mount():
    items = ["alpha", "beta"]
    app = VirtualListApp(items)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        vl = cast(VirtualListView[str], app.query_one(VirtualListView))
        assert vl.count() == 2

        model = cast(ListModel[str], vl._model)  # pyright: ignore[reportPrivateUsage]
        model.append("gamma")
        await model.on_append.asend(["gamma"])
        await pilot.pause()
        assert vl.count() == 3
        assert get_visible_items(vl) == ["alpha", "beta", "gamma"]


@pytest.mark.asyncio
async def test_scroll_to_item():
    items = [f"item_{i}" for i in range(100)]
    app = VirtualListApp(items)
    async with app.run_test(size=(80, 10)) as pilot:
        del pilot  # unused
        vl = cast(VirtualListView[str], app.query_one(VirtualListView))

        vl.scroll_to_item(5)
        visible = get_visible_items(vl)
        assert visible == [f"item_{i}" for i in range(5, 15)]


@pytest.mark.asyncio
async def test_scroll_to_item_out_of_range():
    items = [f"item_{i}" for i in range(10)]
    app = VirtualListApp(items)
    async with app.run_test(size=(80, 10)) as pilot:
        del pilot  # unused
        vl = cast(VirtualListView[str], app.query_one(VirtualListView))

        with pytest.raises(IndexError):
            vl.scroll_to_item(10)

        with pytest.raises(IndexError):
            vl.scroll_to_item(-1)


@dataclass
class Entry:
    label: str
    value: int


def render_entry(item: Entry, index: int) -> RenderableType:
    del index  # unused
    return Text(f"{item.label}: {item.value}", no_wrap=True)


@pytest.mark.asyncio
async def test_complex_items():
    items = [Entry(label=f"entry_{i}", value=i * 10) for i in range(50)]
    app = VirtualListApp(items, render_item=render_entry)
    async with app.run_test(size=(80, 10)) as pilot:
        del pilot  # unused
        vl = cast(VirtualListView[Entry], app.query_one(VirtualListView))

        visible = get_visible_items(vl)
        assert len(visible) == 10
        assert visible[0] == Entry(label="entry_0", value=0)
        assert visible[9] == Entry(label="entry_9", value=90)

        vl.scroll_to_item(5)
        visible = get_visible_items(vl)
        assert visible[0] == Entry(label="entry_5", value=50)


@pytest.mark.asyncio
async def test_cursor_starts_at_zero():
    items = [f"item_{i}" for i in range(10)]
    app = VirtualListApp(items)
    async with app.run_test(size=(80, 10)) as pilot:
        del pilot  # unused
        vl = cast(VirtualListView[str], app.query_one(VirtualListView))
        assert vl.index == 0
        assert vl.follow is False


@pytest.mark.asyncio
async def test_cursor_move_down():
    items = [f"item_{i}" for i in range(10)]
    app = VirtualListApp(items)
    async with app.run_test(size=(80, 10)) as pilot:
        del pilot  # unused
        vl = cast(VirtualListView[str], app.query_one(VirtualListView))
        vl.cursor_down()
        assert vl.index == 1
        vl.cursor_down()
        assert vl.index == 2


@pytest.mark.asyncio
async def test_cursor_move_up():
    items = [f"item_{i}" for i in range(10)]
    app = VirtualListApp(items)
    async with app.run_test(size=(80, 10)) as pilot:
        del pilot  # unused
        vl = cast(VirtualListView[str], app.query_one(VirtualListView))
        vl.cursor_down()
        vl.cursor_down()
        vl.cursor_up()
        assert vl.index == 1


@pytest.mark.asyncio
async def test_cursor_clamps_to_bounds():
    items = [f"item_{i}" for i in range(5)]
    app = VirtualListApp(items)
    async with app.run_test(size=(80, 10)) as pilot:
        del pilot  # unused
        vl = cast(VirtualListView[str], app.query_one(VirtualListView))
        vl.cursor_up()
        assert vl.index == 0

        for _ in range(10):
            vl.cursor_down()
        assert vl.index == 4


@pytest.mark.asyncio
async def test_cursor_scrolls_view_when_past_bottom():
    items = [f"item_{i}" for i in range(100)]
    app = VirtualListApp(items)
    async with app.run_test(size=(80, 10)) as pilot:
        del pilot  # unused
        vl = cast(VirtualListView[str], app.query_one(VirtualListView))

        for _ in range(15):
            vl.cursor_down()
        assert vl.index == 15
        assert vl.scroll_top_index > 0
        visible = get_visible_items(vl)
        assert f"item_{15}" in visible
        assert "item_0" not in visible


def render_multiline(item: str, index: int) -> RenderableType:
    del index  # unused
    return Text(f"{item}\ndetail of {item}")


@pytest.mark.asyncio
async def test_multiline_items_scroll_correctly():
    items = [f"item_{i}" for i in range(100)]
    app = VirtualListApp(items, render_item=render_multiline)
    async with app.run_test(size=(80, 10)) as pilot:
        await pilot.pause()
        vl = cast(VirtualListView[str], app.query_one(VirtualListView))
        # Each item is 2 lines, so 10 lines = 5 visible items
        visible = get_visible_items(vl)
        assert len(visible) == 5

        # Move cursor past the visible area
        for _ in range(6):
            vl.cursor_down()
        assert vl.index == 6
        visible = get_visible_items(vl)
        assert "item_6" in visible


class SelectedCapture(App[None]):
    selected: list[VirtualListView.Selected]

    def __init__(self, items: list[str]) -> None:
        super().__init__()
        self._items = items
        self.selected = []

    @override
    def compose(self) -> ComposeResult:
        model = ListModel(self._items)
        vl: VirtualListView[str] = VirtualListView(
            model=model,  # type: ignore[arg-type]
            render_item=render_str,
        )
        yield vl

    def on_virtual_list_view_selected(self, event: VirtualListView.Selected) -> None:
        self.selected.append(event)


@pytest.mark.asyncio
async def test_selected_event_on_enter():
    items = ["alpha", "beta", "gamma"]
    app = SelectedCapture(items)

    async with app.run_test(size=(80, 10)) as pilot:
        vl = cast(VirtualListView[str], app.query_one(VirtualListView))
        vl.focus()
        vl.cursor_down()

        await pilot.press("enter")
        await pilot.pause()

        assert len(app.selected) == 1
        assert app.selected[0].index == 1
        assert app.selected[0].item == "beta"
        assert app.selected[0].control is vl


class HighlightedCapture(App[None]):
    highlighted: list[VirtualListView.Highlighted]

    def __init__(self, items: list[str]) -> None:
        super().__init__()
        self._items = items
        self.highlighted = []

    @override
    def compose(self) -> ComposeResult:
        model = ListModel(self._items)
        vl: VirtualListView[str] = VirtualListView(
            model=model,  # type: ignore[arg-type]
            render_item=render_str,
        )
        yield vl

    def on_virtual_list_view_highlighted(
        self, event: VirtualListView.Highlighted
    ) -> None:
        self.highlighted.append(event)


@pytest.mark.asyncio
async def test_highlighted_event_on_cursor_move():
    items = ["alpha", "beta", "gamma"]
    app = HighlightedCapture(items)

    async with app.run_test(size=(80, 10)) as pilot:
        vl = cast(VirtualListView[str], app.query_one(VirtualListView))
        vl.focus()
        await pilot.pause()
        app.highlighted.clear()

        vl.cursor_down()
        await pilot.pause()

        assert len(app.highlighted) == 1
        assert app.highlighted[0].index == 1
        assert app.highlighted[0].item == "beta"
        assert app.highlighted[0].control is vl


@pytest.mark.asyncio
async def test_set_index_to_last_multiline():
    items = [f"item_{i}" for i in range(100)]
    app = VirtualListApp(items, render_item=render_multiline)
    async with app.run_test(size=(80, 10)) as pilot:
        await pilot.pause()
        vl = cast(VirtualListView[str], app.query_one(VirtualListView))

        vl.index = 99
        assert vl.index == 99
        visible = get_visible_items(vl)
        assert "item_99" in visible
        assert len(visible) == 5


@pytest.mark.asyncio
async def test_set_index_to_last_single_line():
    items = [f"item_{i}" for i in range(100)]
    app = VirtualListApp(items)
    async with app.run_test(size=(80, 10)) as pilot:
        await pilot.pause()
        vl = cast(VirtualListView[str], app.query_one(VirtualListView))

        vl.index = 99
        assert vl.index == 99
        visible = get_visible_items(vl)
        assert "item_99" in visible
        assert len(visible) == 10


@pytest.mark.asyncio
async def test_cursor_down_scrolls_multiline():
    items = [f"item_{i}" for i in range(100)]
    app = VirtualListApp(items, render_item=render_multiline)
    async with app.run_test(size=(80, 10)) as pilot:
        await pilot.pause()
        vl = cast(VirtualListView[str], app.query_one(VirtualListView))

        # 5 items visible (each 2 lines, viewport 10 lines)
        # Moving to item 5 should scroll
        for _ in range(5):
            vl.cursor_down()

        assert vl.index == 5
        assert vl.scroll_top_index == 1
        visible = get_visible_items(vl)
        assert "item_5" in visible
        assert "item_0" not in visible


@pytest.mark.asyncio
async def test_scroll_viewport_down_single_line():
    items = [f"item_{i}" for i in range(100)]
    app = VirtualListApp(items)
    async with app.run_test(size=(80, 10)) as pilot:
        await pilot.pause()
        vl = cast(VirtualListView[str], app.query_one(VirtualListView))

        assert vl.scroll_top_index == 0
        assert vl.scroll_line_offset == 0

        vl.on_mouse_scroll_down()
        assert vl.scroll_top_index == 1
        assert vl.scroll_line_offset == 0


@pytest.mark.asyncio
async def test_scroll_viewport_up_single_line():
    items = [f"item_{i}" for i in range(100)]
    app = VirtualListApp(items)
    async with app.run_test(size=(80, 10)) as pilot:
        await pilot.pause()
        vl = cast(VirtualListView[str], app.query_one(VirtualListView))

        vl.scroll_to_item(10)
        vl.on_mouse_scroll_up()
        assert vl.scroll_top_index == 9
        assert vl.scroll_line_offset == 0


@pytest.mark.asyncio
async def test_scroll_viewport_down_multiline():
    items = [f"item_{i}" for i in range(100)]
    app = VirtualListApp(items, render_item=render_multiline)
    async with app.run_test(size=(80, 10)) as pilot:
        await pilot.pause()
        vl = cast(VirtualListView[str], app.query_one(VirtualListView))

        # Each item is 2 lines, scroll 1 line → offset into item_0
        vl.on_mouse_scroll_down()
        assert vl.scroll_top_index == 0
        assert vl.scroll_line_offset == 1

        # One more → crosses into item_1
        vl.on_mouse_scroll_down()
        assert vl.scroll_top_index == 1
        assert vl.scroll_line_offset == 0


@pytest.mark.asyncio
async def test_scroll_viewport_up_multiline():
    items = [f"item_{i}" for i in range(100)]
    app = VirtualListApp(items, render_item=render_multiline)
    async with app.run_test(size=(80, 10)) as pilot:
        await pilot.pause()
        vl = cast(VirtualListView[str], app.query_one(VirtualListView))

        vl.scroll_to_item(5)
        assert vl.scroll_top_index == 5
        assert vl.scroll_line_offset == 0

        # Scroll up 1 line: moves into bottom of item_4
        vl.on_mouse_scroll_up()
        assert vl.scroll_top_index == 4
        assert vl.scroll_line_offset == 1

        # One more: back to top of item_4
        vl.on_mouse_scroll_up()
        assert vl.scroll_top_index == 4
        assert vl.scroll_line_offset == 0


@pytest.mark.asyncio
async def test_scroll_viewport_up_clamps_at_top():
    items = [f"item_{i}" for i in range(100)]
    app = VirtualListApp(items)
    async with app.run_test(size=(80, 10)) as pilot:
        await pilot.pause()
        vl = cast(VirtualListView[str], app.query_one(VirtualListView))

        vl.on_mouse_scroll_up()
        assert vl.scroll_top_index == 0
        assert vl.scroll_line_offset == 0


@pytest.mark.asyncio
async def test_scroll_viewport_down_clamps_at_bottom():
    items = [f"item_{i}" for i in range(5)]
    app = VirtualListApp(items)
    async with app.run_test(size=(80, 10)) as pilot:
        await pilot.pause()
        vl = cast(VirtualListView[str], app.query_one(VirtualListView))

        # Only 5 items, all fit in viewport, so scroll should be no-op
        vl.on_mouse_scroll_down()
        assert vl.scroll_top_index == 0
        assert vl.scroll_line_offset == 0


@pytest.mark.asyncio
async def test_scroll_viewport_roundtrip_multiline():
    items = [f"item_{i}" for i in range(100)]
    app = VirtualListApp(items, render_item=render_multiline)
    async with app.run_test(size=(80, 10)) as pilot:
        await pilot.pause()
        vl = cast(VirtualListView[str], app.query_one(VirtualListView))

        # Scroll down then back up should return to origin
        vl.on_mouse_scroll_down()
        assert vl.scroll_top_index == 0
        assert vl.scroll_line_offset == 1

        vl.on_mouse_scroll_up()
        assert vl.scroll_top_index == 0
        assert vl.scroll_line_offset == 0


@pytest.mark.asyncio
async def test_render_includes_partially_visible_bottom_item():
    items = [f"item_{i}" for i in range(100)]
    app = VirtualListApp(items, render_item=render_multiline)
    async with app.run_test(size=(80, 11)) as pilot:
        await pilot.pause()
        vl = cast(VirtualListView[str], app.query_one(VirtualListView))

        rendered = vl.render()
        height = vl._measure_height(rendered)  # pyright: ignore[reportPrivateUsage]
        assert height == 12


@pytest.mark.asyncio
async def test_render_returns_empty_string_when_model_empty():
    app = VirtualListApp[str]([])
    async with app.run_test(size=(80, 10)) as pilot:
        del pilot
        vl = cast(VirtualListView[str], app.query_one(VirtualListView))
        assert vl.render() == ""


@pytest.mark.asyncio
async def test_validate_index_clamps_to_zero_when_empty():
    app = VirtualListApp[str]([])
    async with app.run_test(size=(80, 10)) as pilot:
        del pilot
        vl = cast(VirtualListView[str], app.query_one(VirtualListView))
        vl.index = 5
        assert vl.index == 0


@pytest.mark.asyncio
async def test_cursor_viewport_offset_single_line_in_view():
    items = [f"item_{i}" for i in range(100)]
    app = VirtualListApp(items)
    async with app.run_test(size=(80, 10)) as pilot:
        del pilot
        vl = cast(VirtualListView[str], app.query_one(VirtualListView))
        assert vl.cursor_viewport_offset() == 0
        for _ in range(5):
            vl.cursor_down()
        assert vl.cursor_viewport_offset() == 5


@pytest.mark.asyncio
async def test_cursor_viewport_offset_multiline_after_scroll():
    items = [f"item_{i}" for i in range(100)]
    app = VirtualListApp(items, render_item=render_multiline)
    async with app.run_test(size=(80, 10)) as pilot:
        await pilot.pause()
        vl = cast(VirtualListView[str], app.query_one(VirtualListView))
        for _ in range(5):
            vl.cursor_down()
        assert vl.index == 5
        assert vl.scroll_top_index == 1
        assert vl.cursor_viewport_offset() == 8


@pytest.mark.asyncio
async def test_scroll_to_cursor_offset_roundtrip():
    items = [f"item_{i}" for i in range(100)]
    app = VirtualListApp(items, render_item=render_multiline)
    async with app.run_test(size=(80, 10)) as pilot:
        await pilot.pause()
        vl = cast(VirtualListView[str], app.query_one(VirtualListView))
        for _ in range(10):
            vl.cursor_down()
        before = vl.cursor_viewport_offset()
        top_before = vl.scroll_top_index
        offset_before = vl.scroll_line_offset
        vl.scroll_to_cursor_offset(before)
        assert vl.cursor_viewport_offset() == before
        assert vl.scroll_top_index == top_before
        assert vl.scroll_line_offset == offset_before


@pytest.mark.asyncio
async def test_scroll_to_cursor_offset_beyond_top_clamps():
    items = [f"item_{i}" for i in range(100)]
    app = VirtualListApp(items)
    async with app.run_test(size=(80, 10)) as pilot:
        del pilot
        vl = cast(VirtualListView[str], app.query_one(VirtualListView))
        for _ in range(3):
            vl.cursor_down()
        vl.scroll_to_cursor_offset(10_000)
        assert vl.scroll_top_index == 0
        assert vl.scroll_line_offset == 0


@pytest.mark.asyncio
async def test_scroll_to_cursor_offset_zero_puts_cursor_at_top():
    items = [f"item_{i}" for i in range(100)]
    app = VirtualListApp(items, render_item=render_multiline)
    async with app.run_test(size=(80, 10)) as pilot:
        await pilot.pause()
        vl = cast(VirtualListView[str], app.query_one(VirtualListView))
        for _ in range(5):
            vl.cursor_down()
        vl.scroll_to_cursor_offset(0)
        assert vl.scroll_top_index == 5
        assert vl.scroll_line_offset == 0


@pytest.mark.asyncio
async def test_scroll_half_down_single_line():
    items = [f"item_{i}" for i in range(100)]
    app = VirtualListApp(items)
    async with app.run_test(size=(80, 10)) as pilot:
        del pilot
        vl = cast(VirtualListView[str], app.query_one(VirtualListView))
        vl.scroll_half_down()
        assert vl.index == 5


@pytest.mark.asyncio
async def test_scroll_half_down_multiline():
    items = [f"item_{i}" for i in range(100)]
    app = VirtualListApp(items, render_item=render_multiline)
    async with app.run_test(size=(80, 10)) as pilot:
        await pilot.pause()
        vl = cast(VirtualListView[str], app.query_one(VirtualListView))
        vl.scroll_half_down()
        assert vl.index == 3


@pytest.mark.asyncio
async def test_scroll_half_up_single_line():
    items = [f"item_{i}" for i in range(100)]
    app = VirtualListApp(items)
    async with app.run_test(size=(80, 10)) as pilot:
        del pilot
        vl = cast(VirtualListView[str], app.query_one(VirtualListView))
        vl.index = 20
        vl.scroll_half_up()
        assert vl.index == 15


@pytest.mark.asyncio
async def test_scroll_half_up_multiline():
    items = [f"item_{i}" for i in range(100)]
    app = VirtualListApp(items, render_item=render_multiline)
    async with app.run_test(size=(80, 10)) as pilot:
        await pilot.pause()
        vl = cast(VirtualListView[str], app.query_one(VirtualListView))
        vl.index = 20
        vl.scroll_half_up()
        assert vl.index == 17


@pytest.mark.asyncio
async def test_scroll_half_down_stops_at_last_item():
    items = [f"item_{i}" for i in range(6)]
    app = VirtualListApp(items)
    async with app.run_test(size=(80, 10)) as pilot:
        del pilot
        vl = cast(VirtualListView[str], app.query_one(VirtualListView))
        vl.scroll_half_down()
        assert vl.index == 5


@pytest.mark.asyncio
async def test_scroll_half_up_at_top_stays_at_zero():
    items = [f"item_{i}" for i in range(100)]
    app = VirtualListApp(items)
    async with app.run_test(size=(80, 10)) as pilot:
        del pilot
        vl = cast(VirtualListView[str], app.query_one(VirtualListView))
        vl.scroll_half_up()
        assert vl.index == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "action,expected_index",
    [
        ("action_cursor_down", 11),
        ("action_cursor_up", 9),
        ("action_scroll_half_down", 15),
        ("action_scroll_half_up", 5),
        ("action_jump_top", 0),
    ],
    ids=["down", "up", "half_down", "half_up", "jump_top"],
)
async def test_navigation_actions_clear_follow(
    action: str, expected_index: int
) -> None:
    items = [f"item_{i}" for i in range(100)]
    app = VirtualListApp(items, follow=True)
    async with app.run_test(size=(80, 10)) as pilot:
        await pilot.pause()
        vl = cast(VirtualListView[str], app.query_one(VirtualListView))
        vl.index = 10
        assert vl.follow is True
        getattr(vl, action)()
        assert vl.follow is False
        assert vl.index == expected_index


@pytest.mark.asyncio
async def test_action_jump_bottom_enables_follow():
    items = [f"item_{i}" for i in range(100)]
    app = VirtualListApp(items)
    async with app.run_test(size=(80, 10)) as pilot:
        del pilot
        vl = cast(VirtualListView[str], app.query_one(VirtualListView))
        vl.action_jump_bottom()
        assert vl.follow is True
        assert vl.index == 99


@pytest.mark.asyncio
async def test_action_jump_bottom_on_empty_does_not_crash():
    app = VirtualListApp[str]([])
    async with app.run_test(size=(80, 10)) as pilot:
        del pilot
        vl = cast(VirtualListView[str], app.query_one(VirtualListView))
        vl.action_jump_bottom()
        assert vl.follow is True


@pytest.mark.asyncio
async def test_ensure_cursor_visible_when_cursor_above_viewport():
    items = [f"item_{i}" for i in range(100)]
    app = VirtualListApp(items)
    async with app.run_test(size=(80, 10)) as pilot:
        del pilot
        vl = cast(VirtualListView[str], app.query_one(VirtualListView))
        vl.scroll_to_item(20)
        vl.index = 5
        assert vl.scroll_top_index == 5
        assert vl.scroll_line_offset == 0


@pytest.mark.asyncio
async def test_append_with_follow_jumps_to_new_last():
    items = ["alpha", "beta"]
    app = VirtualListApp(items, follow=True)
    async with app.run_test(size=(80, 10)) as pilot:
        await pilot.pause()
        vl = cast(VirtualListView[str], app.query_one(VirtualListView))
        model = cast(ListModel[str], vl._model)  # pyright: ignore[reportPrivateUsage]
        model.append("gamma")
        await model.on_append.asend(["gamma"])
        await pilot.pause()
        assert vl.index == 2


@pytest.mark.asyncio
async def test_append_to_empty_non_followed_sets_index_to_zero():
    app = VirtualListApp[str]([])
    async with app.run_test(size=(80, 10)) as pilot:
        await pilot.pause()
        vl = cast(VirtualListView[str], app.query_one(VirtualListView))
        assert vl.index == -1
        model = cast(ListModel[str], vl._model)  # pyright: ignore[reportPrivateUsage]
        model.append("first")
        await model.on_append.asend(["first"])
        await pilot.pause()
        assert vl.index == 0


@pytest.mark.asyncio
async def test_append_to_non_empty_non_followed_preserves_index():
    items = ["alpha", "beta", "gamma"]
    app = VirtualListApp(items)
    async with app.run_test(size=(80, 10)) as pilot:
        await pilot.pause()
        vl = cast(VirtualListView[str], app.query_one(VirtualListView))
        vl.index = 1
        model = cast(ListModel[str], vl._model)  # pyright: ignore[reportPrivateUsage]
        model.append("delta")
        await model.on_append.asend(["delta"])
        await pilot.pause()
        assert vl.index == 1
