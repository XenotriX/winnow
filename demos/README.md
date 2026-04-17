# Demos

Scripted scenarios that showcase specific jnav features. Each subdirectory is self-contained: the generator pipes JSONL directly into `jnav`, and the `.tape` file drives a [VHS](https://github.com/charmbracelet/vhs) recording.

## Scenarios

- **`filtering/`**: builds a nested jq filter `.path == "/api/orders" AND (.status >= 500 OR .latency_ms > 1000) AND (.is_admin | not)`, moving clauses between groups and negating them.
- **`selectors/`**: showcases non-trivial jq selectors: splitting a string to extract a number, list aggregation with `length`, and per-item string interpolation with `map("\(.name): \(.qty)")`.

## Running

Each directory has a `generate.py` (standalone PEP 723 script, dependencies declared inline, run via `uv run`) and a `demo.tape` renderable with `vhs`.

Pipe a generator straight into jnav to explore interactively:

```bash
uv run demos/filtering/generate.py | uv run jnav
```

Render a recording:

```bash
vhs demos/filtering/demo.tape
```

All generators accept `--seed <int>` for reproducible output.
