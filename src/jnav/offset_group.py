from __future__ import annotations

from collections.abc import Generator

from rich.console import Console, ConsoleOptions, Group, RenderableType
from rich.segment import Segment


class OffsetGroup:
    """A Rich renderable that renders a group of items, skipping the first N lines.

    Used by VirtualListView to handle partial visibility of the topmost item
    when the viewport is scrolled partway into it.
    """

    def __init__(
        self,
        renderables: list[RenderableType],
        skip_lines: int,
    ) -> None:
        self._group = Group(*renderables)
        self._skip = skip_lines

    def __rich_console__(
        self, console: Console, options: ConsoleOptions
    ) -> Generator[Segment, None, None]:
        segments = console.render(self._group, options)
        for i, line in enumerate(Segment.split_lines(segments)):
            if i < self._skip:
                continue
            yield from line
            yield Segment.line()
