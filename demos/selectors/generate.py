#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.14"
# dependencies = ["click>=8.1.0"]
# ///

from __future__ import annotations

import json
import random
from datetime import UTC, datetime, timedelta
from typing import Any

import click

LogEntry = dict[str, Any]

ITEM_NAMES = [
    "widget",
    "gadget",
    "sprocket",
    "doohickey",
    "thingamajig",
    "whatsit",
]
VERSIONS = ["v2.4.1", "v2.4.2", "v2.5.0", "v2.5.1", "v3.0.0"]
METHODS = ["POST", "PATCH"]

USER_AGENTS = [
    "Mozilla/5.0 (iPhone; CPU iPhone OS 14_2 like Mac OS X) AppleWebKit/605.1.15 Version/14.0 Safari/605.1.15",
    "Mozilla/5.0 (iPad; CPU OS 15_3_1 like Mac OS X) AppleWebKit/605.1.15 Version/15.0 Safari/605.1.15",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_4 like Mac OS X) AppleWebKit/605.1.15 Version/16.4 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPod; CPU iPhone OS 13_5_1 like Mac OS X) AppleWebKit/605.1.15 Version/13.0 Mobile/15E148 Safari/604.1",
]


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
        for i in range(120):
            when = start + timedelta(seconds=i * 2 + random.uniform(0, 1))
            n_items = random.randint(2, 5)
            items = [
                {"name": random.choice(ITEM_NAMES), "qty": random.randint(1, 50)}
                for _ in range(n_items)
            ]
            entry: LogEntry = {
                "ts": ts(when),
                "level": "info",
                "service": "api",
                "message": "batch processed",
                "request": {
                    "method": random.choice(METHODS),
                    "path": "/api/batch",
                    "headers": {
                        "user_agent": random.choice(USER_AGENTS),
                        "x-client-version": random.choice(VERSIONS),
                    },
                },
                "items": items,
                "total_qty": sum(it["qty"] for it in items),
                "build": when.strftime("%Y.%m.%d-%H%M"),
                "version": random.choice(VERSIONS),
                "instance": f"api-{random.randint(1, 8):02d}",
            }
            click.echo(json.dumps(entry, separators=(",", ":"), ensure_ascii=False))
    except BrokenPipeError:
        pass


if __name__ == "__main__":
    main()
