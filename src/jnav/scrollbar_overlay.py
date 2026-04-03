from __future__ import annotations

from collections.abc import Generator

from rich.color import Color
from rich.console import Console, ConsoleOptions, RenderableType
from rich.segment import Segment
from rich.style import Style


def _get_bg_at(line: list[Segment], position: int) -> Color | None:
    pos = 0
    for seg in line:
        pos += seg.cell_length
        if pos > position:
            return seg.style.bgcolor if seg.style else None
    return None


class ScrollbarOverlay:
    """A Rich renderable that overlays a scrollbar thumb on inner content.

    Renders the inner content normally, but on lines within the thumb region,
    truncates the line by one character and appends a scrollbar indicator.
    The thumb character inherits the background color from the content beneath it.
    """

    def __init__(
        self,
        inner: RenderableType,
        *,
        total_items: int,
        visible_count: int,
        scroll_position: int,
        thumb_style: Style,
    ) -> None:
        self._inner = inner
        self._total_items = total_items
        self._visible_count = visible_count
        self._scroll_position = scroll_position
        self._thumb_style = thumb_style

    def _compute_thumb(self, viewport_height: int) -> tuple[int, int]:
        max_scroll = self._total_items - self._visible_count
        if max_scroll <= 0:
            return 0, 0
        thumb_size = max(
            1, round(viewport_height * self._visible_count / self._total_items)
        )
        fraction = self._scroll_position / max_scroll
        thumb_top = round(fraction * (viewport_height - thumb_size))
        thumb_top = max(0, min(thumb_top, viewport_height - thumb_size))
        return thumb_top, thumb_top + thumb_size

    def __rich_console__(
        self,
        console: Console,
        options: ConsoleOptions,
    ) -> Generator[Segment, None, None]:
        width = options.max_width
        height = options.height or options.max_height

        thumb_top, thumb_end = self._compute_thumb(height)

        segments = console.render(self._inner, options)
        for y, line in enumerate(Segment.split_lines(segments)):
            # Yield the line as-is if it's outside the thumb region
            if not (thumb_top <= y < thumb_end):
                yield from line
                yield Segment.line()
                continue

            # Truncate the line to make room for the scrollbar
            truncated = Segment.adjust_line_length(list(line), width - 1)
            yield from truncated

            # Get the background color of the wrapped renderable
            bg = _get_bg_at(line, width - 1)

            yield Segment("┃", Style(color=self._thumb_style.color, bgcolor=bg))
            yield Segment.line()
