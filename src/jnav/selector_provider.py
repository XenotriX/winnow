import functools
from typing import cast

import jq
from aioreactive import AsyncSubject
from pydantic import BaseModel

from jnav.json_model import JsonValue, to_json


@functools.lru_cache(maxsize=32)
def _compile_jq(expression: str):
    return jq.compile(expression)


class Selector(BaseModel):
    expression: str
    enabled: bool = True

    def resolve(self, entry: JsonValue) -> JsonValue:
        """Extract this selector's value from `entry`."""
        try:
            results = _compile_jq(self.expression).input_text(to_json(entry)).all()
            results = cast(list[JsonValue], results)
        except ValueError:
            return None
        if len(results) == 1:
            return results[0]
        return results


class SelectorProvider:
    """Tracks user-defined jq selectors for extracting values from entries."""

    on_change: AsyncSubject[None]

    def __init__(self) -> None:
        self._selectors: list[Selector] = []
        self.on_change = AsyncSubject[None]()

    @property
    def selectors(self) -> list[Selector]:
        return list(self._selectors)

    @property
    def active_selectors(self) -> list[Selector]:
        return [s for s in self._selectors if s.enabled]

    def has_selector(self, expression: str) -> bool:
        return any(s.expression == expression for s in self._selectors)

    async def add_selector(self, expression: str) -> None:
        self._selectors.append(Selector(expression=expression, enabled=True))
        await self.on_change.asend(None)

    async def insert_selector(self, index: int, expression: str) -> None:
        self._selectors.insert(index, Selector(expression=expression, enabled=True))
        await self.on_change.asend(None)

    async def remove_selector(self, index: int) -> None:
        self._selectors.pop(index)
        await self.on_change.asend(None)

    async def remove_selector_by_expression(self, expression: str) -> None:
        for i, s in enumerate(self._selectors):
            if s.expression == expression:
                self._selectors.pop(i)
                await self.on_change.asend(None)
                return

    async def toggle_selector(self, index: int) -> None:
        self._selectors[index].enabled = not self._selectors[index].enabled
        await self.on_change.asend(None)

    async def edit_selector(self, index: int, expression: str) -> None:
        self._selectors[index].expression = expression
        await self.on_change.asend(None)

    async def set_selectors(self, selectors: list[Selector]) -> None:
        self._selectors = list(selectors)
        await self.on_change.asend(None)

    async def clear_selectors(self) -> None:
        self._selectors.clear()
        await self.on_change.asend(None)
