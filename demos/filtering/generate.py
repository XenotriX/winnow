#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.14"
# dependencies = ["click>=8.1.0"]
# ///

from __future__ import annotations

import json
import random
from datetime import UTC, datetime, timedelta

import click

PATHS_METHODS = [
    ("GET", "/api/orders"),
    ("POST", "/api/orders"),
    ("GET", "/api/users"),
    ("GET", "/api/items"),
    ("POST", "/api/auth"),
    ("GET", "/health"),
]

USERS = [
    {"id": "u_alice", "admin": True},
    {"id": "u_bob", "admin": False},
    {"id": "u_carol", "admin": False},
    {"id": "u_dave", "admin": True},
    {"id": "u_eve", "admin": False},
    {"id": "u_frank", "admin": False},
]

STATUSES = [200, 201, 401, 403, 404, 500, 502, 503]
STATUS_WEIGHTS = [0.62, 0.05, 0.06, 0.03, 0.09, 0.09, 0.04, 0.02]

LATENCY_BUCKETS = [(5, 50), (80, 500), (800, 2500)]
LATENCY_BUCKET_WEIGHTS = [0.6, 0.3, 0.1]


def ts(dt: datetime) -> str:
    return (
        dt.astimezone(UTC)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


@click.command()
@click.option("--seed", type=int, default=42, show_default=True)
def main(seed: int) -> None:
    random.seed(seed)
    start = datetime(2026, 4, 16, 14, 0, 0, tzinfo=UTC)

    try:
        for i in range(400):
            when = start + timedelta(
                seconds=i * 0.5 + random.uniform(0, 0.25)
            )
            user = random.choice(USERS)
            method, path = random.choice(PATHS_METHODS)
            status = random.choices(STATUSES, STATUS_WEIGHTS)[0]
            low, high = random.choices(LATENCY_BUCKETS, LATENCY_BUCKET_WEIGHTS)[0]
            latency_ms = round(random.uniform(low, high), 2)
            entry = {
                "ts": ts(when),
                "level": (
                    "error"
                    if status >= 500
                    else ("warning" if status >= 400 else "info")
                ),
                "service": "api",
                "message": f"response {status}",
                "path": path,
                "method": method,
                "status": status,
                "latency_ms": latency_ms,
                "user_id": user["id"],
                "is_admin": user["admin"],
            }
            click.echo(json.dumps(entry, separators=(",", ":"), ensure_ascii=False))
    except BrokenPipeError:
        pass


if __name__ == "__main__":
    main()
