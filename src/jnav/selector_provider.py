from typing import TypedDict

from aioreactive import AsyncSubject


class Selector(TypedDict):
    path: str
    enabled: bool


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
    def active_selectors(self) -> list[str]:
        return [s["path"] for s in self._selectors if s["enabled"]]

    def has_selector(self, path: str) -> bool:
        return any(s["path"] == path for s in self._selectors)

    async def add_selector(self, path: str) -> None:
        self._selectors.append({"path": path, "enabled": True})
        await self.on_change.asend(None)

    async def insert_selector(self, index: int, path: str) -> None:
        self._selectors.insert(index, {"path": path, "enabled": True})
        await self.on_change.asend(None)

    async def remove_selector(self, index: int) -> None:
        self._selectors.pop(index)
        await self.on_change.asend(None)

    async def remove_selector_by_path(self, path: str) -> None:
        for i, s in enumerate(self._selectors):
            if s["path"] == path:
                self._selectors.pop(i)
                await self.on_change.asend(None)
                return

    async def toggle_selector(self, index: int) -> None:
        self._selectors[index]["enabled"] = not self._selectors[index]["enabled"]
        await self.on_change.asend(None)

    async def edit_selector(self, index: int, path: str) -> None:
        self._selectors[index]["path"] = path
        await self.on_change.asend(None)

    async def set_selectors(self, selectors: list[Selector]) -> None:
        self._selectors = list(selectors)
        await self.on_change.asend(None)

    async def clear_selectors(self) -> None:
        self._selectors.clear()
        await self.on_change.asend(None)
