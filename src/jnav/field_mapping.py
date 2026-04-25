from datetime import datetime
from typing import Literal

from pydantic import BaseModel

TimestampFormat = Literal["iso8601", "epoch_s", "epoch_ms", "epoch_us", "epoch_ns"]


class TimestampField(BaseModel):
    path: str
    format: TimestampFormat


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


def detect_timestamp_format(value: object) -> TimestampFormat | None:
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
