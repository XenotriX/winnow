<p>
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://github.com/XenotriX/jnav/blob/d28e3701ec1fa795958db0da7293169ff2887e58/docs/logo/jnav_logo_dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="https://github.com/XenotriX/jnav/blob/d28e3701ec1fa795958db0da7293169ff2887e58/docs/logo/jnav_logo_light.svg">
    <img alt="jnav" src="https://github.com/XenotriX/jnav/blob/d28e3701ec1fa795958db0da7293169ff2887e58/docs/logo/jnav_logo_dark.svg">
  </picture>
</p>

Interactive JSON log viewer with [jq](https://jqlang.github.io/jq/) filtering. Navigate, search, filter, and inspect structured logs in the terminal.

![screenshot](https://github.com/XenotriX/jnav/blob/360911e954d91e267616508384ca2e7814c22913/screenshot.png)

## Install

```bash
uv tool install jnav
```

or

```bash
pipx install jnav
```

## Usage

```bash
# Open a log file
$ jnav app.log

# Follow the file for new entries (like tail -f)
$ jnav --follow app.log

# Pipe JSONL from stdin
$ cat logs.jsonl | jnav
```

## Features

### Filtering

Filters use jq expressions. Clauses are organized in a tree of AND/OR groups, which gets compiled into a single jq expression used to evaluate each entry.

```python
.level == "error"                                   # exact match
.data.user_id | IN("abc123", "def456", "ghi789")    # match any of
.message | contains("timeout")                      # substring
.message | test("connection (refused|reset)")       # regex
.status >= 500                                      # numeric comparison
.items | any(.name == "widget")                     # list predicate
```

https://github.com/user-attachments/assets/4c5fa668-7c37-4b59-97f5-4962aeb12504

### Selected Fields

Selectors are jq expressions evaluated per entry, rendered inline next to the summary. They can index arrays, aggregate, or reshape strings.

```python
.status                                # plain field
.items[0].name                         # array index
.items | length                        # computed
.items | map("\(.name): \(.qty)")      # string interpolation over a list
.build | split("-")[1] | tonumber      # extract a number from a string
.request.headers.user_agent            # deep path
```

Add from the detail panel with `s`, or open the selectors manager with `S` to add, edit, reorder, and toggle them.


https://github.com/user-attachments/assets/a9e93048-c3e8-44e6-9f82-727b8e9f8d10

### JSON String Expansion

Values that are JSON-encoded strings (e.g. `"data": "{\"key\": \"value\"}"`) are automatically parsed and displayed as nested objects. The tree view shows `"{}"` in italic to distinguish them from real objects. Filters and selectors work through expanded JSON strings transparently.

### Live Tailing

With `--follow`, jnav watches the file for new lines (like `tail -f`). New entries are parsed, filtered, and appended to the view. If you're at the bottom of the list, it auto-scrolls to show new entries.

### Session Persistence

Filters, selected fields, scroll position, panel state, and search terms are saved when you quit and restored when reopening the same file. State is stored in `~/.local/share/jnav/`.

## Keybindings

### Navigation

| Key                 | Action                      |
| ------------------- | --------------------------- |
| `j` / `k`           | Move up/down                |
| `gg` / `G`          | Jump to first/last entry    |
| `Ctrl+D` / `Ctrl+U` | Half-page scroll            |
| `h` / `l`           | Focus list / detail panel   |
| `Enter`             | Inspect entry (open detail) |
| `Escape`            | Back                        |

### Search and Filter

| Key       | Action                                             |
| --------- | -------------------------------------------------- |
| `/`       | Search (highlights matches, does not hide entries) |
| `n` / `N` | Next / previous search match                       |
| `F`       | Filter manager (jq expressions)                    |
| `ft`      | Quick text filter                                  |
| `fp`      | Pause / resume filters                             |
| `Escape`  | Clear search                                       |
| `r`       | Reset filters, fields, and search                  |

### Display

| Key  | Action                                   |
| ---- | ---------------------------------------- |
| `S`  | Selected fields manager                  |
| `vi` | Toggle inline expanded tree in list rows |
| `d`  | Toggle detail panel                      |
| `?`  | Help                                     |
| `q`  | Quit                                     |

### Detail Panel

| Key  | Action                                   |
| ---- | ---------------------------------------- |
| `s`  | Select (or deselect) the field           |
| `ff` | Filter by value of the highlighted field |
| `fn` | Filter: entries that have this field     |
| `ve` | View the value in `$EDITOR`              |
| `vo` | Show only selected fields                |

### Filter Manager

| Key             | Action                     |
| --------------- | -------------------------- |
| `a`             | Add filter clause          |
| `g`             | Add group                  |
| `e`             | Edit clause                |
| `d` / `y` / `p` | Cut / yank / paste         |
| `t`             | Enable / disable           |
| `o`             | Toggle AND / OR on a group |
| `n`             | Negate                     |
| `c`             | Flatten group              |
| `r`             | Rename                     |
| `Escape`        | Close                      |

### Selected Fields Manager

| Key             | Action             |
| --------------- | ------------------ |
| `a`             | Add selector       |
| `e`             | Edit selector      |
| `d` / `y` / `p` | Cut / yank / paste |
| `t`             | Enable / disable   |
| `Escape`        | Close              |

## Credits

- [lnav](https://github.com/tstack/lnav): the main inspiration: an interactive log viewer with structured querying
- [hl](https://github.com/pamburus/hl): shaped several design decisions around how JSON log entries should look
- [Open Color](https://yeun.github.io/open-color/): the palette the theme is built on
