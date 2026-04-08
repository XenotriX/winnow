from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

TimestampFormat = Literal["iso8601", "epoch_s", "epoch_ms", "epoch_us", "epoch_ns"]


class TimestampField(BaseModel):
    path: str
    format: TimestampFormat


def _build_timestamp(path: str, value: object) -> TimestampField | None:
    fmt = _detect_timestamp_format(value)
    return TimestampField(path=path, format=fmt) if fmt is not None else None


def _build_string_role(path: str, value: object) -> str | None:
    return path if value not in (None, "") else None


@dataclass(frozen=True)
class RoleSpec:
    name: str
    candidates: list[str]
    build: Callable[[str, object], object | None]


ROLES: list[RoleSpec] = [
    RoleSpec(
        name="timestamp",
        candidates=[
            "@timestamp",
            "timestamp",
            "ts",
            "time",
            "@t",
            "asctime",
            "eventTime",
            "Timestamp",
        ],
        build=_build_timestamp,
    ),
    RoleSpec(
        name="level",
        candidates=[
            "level",
            "severity",
            "levelname",
            "@l",
            "log_level",
            "loglevel",
            "SeverityText",
        ],
        build=_build_string_role,
    ),
    RoleSpec(
        name="message",
        candidates=[
            "message",
            "msg",
            "@m",
            "event",
            "Body",
            "log",
        ],
        build=_build_string_role,
    ),
]


class FieldMapping(BaseModel):
    timestamp: TimestampField | None = None
    level: str | None = None
    message: str | None = None

    def assignments(self) -> dict[str, object | None]:
        return {
            "timestamp": self.timestamp,
            "level": self.level,
            "message": self.message,
        }

    def missing_roles(self) -> list[str]:
        return [name for name, value in self.assignments().items() if value is None]


def detect_role_updates(
    mapping: FieldMapping,
    entry: dict[str, object],
    new_fields: set[str],
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
            built = role.build(candidate, entry.get(candidate))
            if built is not None:
                updates[role.name] = built
                break
    return updates


def _detect_timestamp_format(value: object) -> TimestampFormat | None:
    if isinstance(value, str) and value:
        try:
            _ = datetime.fromisoformat(value)
            return "iso8601"
        except ValueError:
            return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return _epoch_format_from_magnitude(float(value))
    return None


def _epoch_format_from_magnitude(value: float) -> TimestampFormat:
    magnitude = abs(value)
    if magnitude < 1e11:
        return "epoch_s"
    if magnitude < 1e14:
        return "epoch_ms"
    if magnitude < 1e17:
        return "epoch_us"
    return "epoch_ns"

