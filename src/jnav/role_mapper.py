import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from aioreactive import AsyncSubject

from jnav.field_mapping import FieldMapping, TimestampField, detect_timestamp_format
from jnav.json_model import JsonObject, JsonValue, walk
from jnav.node_path import NodePath
from jnav.store import IndexedEntry

logger = logging.getLogger(__name__)


def _build_timestamp(path: NodePath, value: object) -> TimestampField | None:
    fmt = detect_timestamp_format(value)
    return TimestampField(path=str(path), format=fmt) if fmt is not None else None


def _build_string_role(path: NodePath, value: object) -> str | None:
    return str(path) if value not in (None, "") else None


def _detect_role_updates(
    mapping: FieldMapping,
    entry: JsonObject,
    new_fields: set[NodePath],
) -> dict[str, object]:
    """Detect updates to the field mapping based on a new entry.
    For each role, if it's not already set in the mapping, check the candidate fields.
    If a candidate field is present in the new fields, attempt to build the role value.
    If successful, add it to the updates dict.
    """
    updates: dict[str, object] = {}
    current = mapping.assignments()
    for role in ROLES:
        if current[role.name] is not None:
            continue
        for candidate in role.candidates:
            if candidate not in new_fields:
                continue
            built = role.build(candidate, candidate.resolve(entry))
            if built is not None:
                updates[role.name] = built
                break
    return updates


@dataclass(frozen=True)
class RoleSpec:
    name: str
    candidates: list[NodePath]
    build: Callable[[NodePath, object], object | None]


ROLES: list[RoleSpec] = [
    RoleSpec(
        name="timestamp",
        candidates=[
            NodePath("@timestamp"),
            NodePath("timestamp"),
            NodePath("ts"),
            NodePath("time"),
            NodePath("@t"),
            NodePath("asctime"),
            NodePath("eventTime"),
            NodePath("Timestamp"),
        ],
        build=_build_timestamp,
    ),
    RoleSpec(
        name="level",
        candidates=[
            NodePath("level"),
            NodePath("severity"),
            NodePath("levelname"),
            NodePath("@l"),
            NodePath("log_level"),
            NodePath("loglevel"),
            NodePath("SeverityText"),
        ],
        build=_build_string_role,
    ),
    RoleSpec(
        name="message",
        candidates=[
            NodePath("message"),
            NodePath("msg"),
            NodePath("@m"),
            NodePath("event"),
            NodePath("Body"),
            NodePath("log"),
        ],
        build=_build_string_role,
    ),
]


class RoleMapper:
    """Tracks fields discovered in the data and the timestamp/level/message role mapping."""

    on_change: AsyncSubject[None]

    def __init__(self) -> None:
        self._all_fields: set[NodePath] = set()
        self._mapping: FieldMapping = FieldMapping()
        self.on_change = AsyncSubject[None]()

    @property
    def all_fields(self) -> set[str]:
        return {str(f) for f in self._all_fields}

    @property
    def mapping(self) -> FieldMapping:
        if len(self._mapping.missing_roles()) == 3:
            # If no roles have been assigned, treat all fields as candidates for all roles
            return FieldMapping(
                timestamp=None,
                level=None,
                message=".",
            )

        return self._mapping

    async def discover(self, entries: list[IndexedEntry]) -> None:
        """Discover fields from a list of entries. Updates the mapping if new roles are detected."""
        for ie in entries:
            await self.discover_from_entry(ie.entry.expanded)

    async def discover_from_entry(self, entry: JsonValue) -> None:
        """Discover fields from a single entry. Updates the mapping if new roles are detected."""
        if not isinstance(entry, dict):
            return
        entry_fields = {p for _, p in walk(entry)}
        new_fields = entry_fields - self._all_fields
        self._all_fields.update(new_fields)

        updates = _detect_role_updates(self._mapping, entry, new_fields)

        if not updates:
            return

        self._mapping = self._mapping.model_copy(update=updates)
        await self.on_change.asend(None)

    async def set_mapping(
        self,
        mapping_data: dict[str, Any] | FieldMapping | None,
    ) -> None:
        if mapping_data:
            self._mapping = FieldMapping.model_validate(mapping_data)
        else:
            self._mapping = FieldMapping()
        await self.on_change.asend(None)
