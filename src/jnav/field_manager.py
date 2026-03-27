from typing import Any, TypedDict, cast

from aioreactive import AsyncSubject

from jnav.store import IndexedEntry

PRIORITY_KEYS = ("timestamp", "ts", "time", "level", "severity", "message", "msg")


def flatten_keys(obj: dict[str, Any], prefix: str = "") -> list[str]:
    keys: list[str] = []
    for k, v in obj.items():
        full = f"{prefix}{k}"
        if isinstance(v, dict):
            v = cast(dict[str, Any], v)
            for sub_k in v:
                keys.append(f"{full}.{sub_k}")
        else:
            keys.append(full)
    return keys


class FieldSelector(TypedDict):
    path: str
    enabled: bool


class FieldManager:
    on_change: AsyncSubject[None]

    def __init__(self) -> None:
        self._all_fields: list[str] = []
        self._all_fields_set: set[str] = set()
        self._base_fields: list[str] = []
        self._custom_fields: list[FieldSelector] = []
        self.on_change = AsyncSubject[None]()

    @property
    def all_fields(self) -> list[str]:
        return self._all_fields

    @property
    def base_fields(self) -> list[str]:
        return self._base_fields

    @property
    def custom_fields(self) -> list[FieldSelector]:
        return list(self._custom_fields)

    @property
    def active_fields(self) -> list[str]:
        return self._base_fields + [
            f["path"] for f in self._custom_fields if f["enabled"]
        ]

    @property
    def custom_fields_set(self) -> set[str]:
        return {f["path"] for f in self._custom_fields if f["enabled"]}

    def discover(self, entries: list[IndexedEntry]) -> None:
        was_empty = not self._all_fields
        for ie in entries:
            for key in flatten_keys(ie.entry.expanded):
                if key not in self._all_fields_set:
                    self._all_fields_set.add(key)
                    self._all_fields.append(key)
        if was_empty and self._all_fields:
            self._base_fields = [k for k in PRIORITY_KEYS if k in self._all_fields_set]

    async def add_field(self, path: str) -> None:
        existing = {f["path"] for f in self._custom_fields}
        if path in existing:
            return
        self._custom_fields.append({"path": path, "enabled": True})
        await self.on_change.asend(None)

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
