from typing import Literal

from aioreactive import AsyncSubject
from jnav.filtering import Filter


class FilterProvider:
    _filters: list[Filter]
    on_change: AsyncSubject[None]

    def __init__(self):
        self._filters = []
        self.on_change = AsyncSubject[None]()

    async def add_filter(
        self,
        expr: str,
        label: str | None = None,
        combine: Literal["and", "or"] = "and",
    ) -> None:
        """Add a new filter."""
        existing = {f["expr"] for f in self._filters}
        if expr not in existing:
            entry: Filter = {
                "expr": expr,
                "enabled": True,
                "combine": combine,
            }
            if label:
                entry["label"] = label
            self._filters.append(entry)
            await self.on_change.asend(None)

    async def toggle_filter(self, index: int) -> None:
        self._filters[index]["enabled"] = not self._filters[index]["enabled"]
        await self.on_change.asend(None)

    async def toggle_combine(self, index: int) -> None:
        current = self._filters[index].get("combine", "and")
        self._filters[index]["combine"] = "or" if current == "and" else "and"
        await self.on_change.asend(None)

    async def remove_filter(self, index: int) -> None:
        self._filters.pop(index)
        await self.on_change.asend(None)

    async def edit_filter(self, index: int, expr: str) -> None:
        self._filters[index]["expr"] = expr
        self._filters[index].pop("label", None)
        await self.on_change.asend(None)

    async def clear_filters(self) -> None:
        self._filters.clear()
        await self.on_change.asend(None)

    def get_filters(self) -> list[Filter]:
        return list(self._filters)

    async def set_filters(self, filters: list[Filter]) -> None:
        self._filters = list(filters)
        await self.on_change.asend(None)
