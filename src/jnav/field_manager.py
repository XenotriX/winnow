from typing import Any, TypedDict

from aioreactive import AsyncSubject

from jnav.field_mapping import FieldMapping, detect_role_updates
from jnav.store import IndexedEntry


class FieldSelector(TypedDict):
    path: str
    enabled: bool


class FieldManager:
    on_change: AsyncSubject[None]

    def __init__(self) -> None:
        self._all_fields: set[str] = set()
        self._custom_fields: list[FieldSelector] = []
        self._mapping: FieldMapping = FieldMapping()
        self.on_change = AsyncSubject[None]()

    @property
    def all_fields(self) -> set[str]:
        return self._all_fields

    @property
    def custom_fields(self) -> list[FieldSelector]:
        return list(self._custom_fields)

    @property
    def active_fields(self) -> set[str]:
        return {f["path"] for f in self._custom_fields if f["enabled"]}

    @property
    def mapping(self) -> FieldMapping:
        return self._mapping

    async def discover(self, entries: list[IndexedEntry]) -> None:
        """Discover fields from a list of entries.
        Updates the mapping if new fields are found.
        """
        for ie in entries:
            await self.discover_from_entry(ie.entry.expanded)

    async def discover_from_entry(self, entry: dict[str, Any]) -> None:
        """Discover fields from a single entry.
        Updates the mapping if new fields are found."""
        new_fields = entry.keys() - self._all_fields
        self._all_fields.update(new_fields)

        updates = detect_role_updates(self._mapping, entry, new_fields)

        if not updates:
            return

        self._mapping = self._mapping.model_copy(update=updates)
        await self.on_change.asend(None)

    async def set_mapping(self, mapping_data: dict[str, Any] | FieldMapping | None) -> None:
        if mapping_data:
            self._mapping = FieldMapping.model_validate(mapping_data)
        else:
            self._mapping = FieldMapping()
        await self.on_change.asend(None)

    def has_field(self, path: str) -> bool:
        return any(f["path"] == path for f in self._custom_fields)

    async def add_field(self, path: str) -> None:
        if self.has_field(path):
            return
        self._custom_fields.append({"path": path, "enabled": True})
        await self.on_change.asend(None)

    async def remove_field_by_path(self, path: str) -> None:
        for i, f in enumerate(self._custom_fields):
            if f["path"] == path:
                self._custom_fields.pop(i)
                await self.on_change.asend(None)
                return

    async def toggle_field(self, index: int) -> None:
        self._custom_fields[index]["enabled"] = not self._custom_fields[index][
            "enabled"
        ]
        await self.on_change.asend(None)

    async def remove_field(self, index: int) -> None:
        self._custom_fields.pop(index)
        await self.on_change.asend(None)

    async def edit_field(self, index: int, path: str) -> None:
        self._custom_fields[index]["path"] = path
        await self.on_change.asend(None)

    async def set_custom_fields(self, fields: list[FieldSelector]) -> None:
        self._custom_fields = list(fields)
        await self.on_change.asend(None)

    async def clear_custom_fields(self) -> None:
        self._custom_fields.clear()
        await self.on_change.asend(None)
