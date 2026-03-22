import hashlib
from pathlib import Path
import sys
import click
from .app import JnavApp
from .parsing import parse_entries

_STATE_DIR = Path.home() / ".local" / "share" / "jnav"

def _state_file_for(file_path: str) -> Path:
    key = hashlib.sha256(str(Path(file_path).resolve()).encode()).hexdigest()[:16]
    return _STATE_DIR / f"{key}.json"

@click.command()
@click.argument("file", required=False, type=click.Path(exists=True))
@click.option("-f", "--filter", "initial_filter", default="", help="Initial jq filter expression")
def main(file: str | None, initial_filter: str) -> None:
    """Interactive JSON log viewer with jq filtering."""
    tail_path: str | None = None
    tail_offset: int = 0

    if file:
        with open(file) as f:
            lines = f.readlines()
            tail_offset = f.tell()
        tail_path = file
    elif not sys.stdin.isatty():
        lines = sys.stdin.readlines()
        sys.stdin.close()
        sys.stdin = open("/dev/tty")
    else:
        click.echo("Usage: jnav [FILE] or pipe JSONL via stdin", err=True)
        raise SystemExit(1)

    entries = parse_entries(lines)
    if not entries:
        click.echo("No valid JSON entries found.", err=True)
        raise SystemExit(1)

    state_file = _state_file_for(file) if file else None
    app = JnavApp(
        entries=entries,
        initial_filter=initial_filter,
        tail_path=tail_path,
        tail_offset=tail_offset,
        state_file=state_file,
    )
    app.title = "jnav"
    app.run()


if __name__ == "__main__":
    main()
