# md-mcp

An MCP server that gives agents surgical read/write access to individual sections of Markdown files.

## Overview

Large Markdown files — documentation, changelogs, wikis — are expensive for agents to work with: reading the
entire file just to update one section wastes tokens, and rewriting the whole file risks accidental data loss.
md-mcp solves this by exposing each section as an individually addressable unit, so an agent can fetch, edit,
or delete exactly the slice it needs without touching anything else.

The server runs over stdio as a local MCP server. Files are addressed by path on disk; sections within a file
are addressed by a dot-separated heading path (e.g. `"User Guide.Installation.Prerequisites"`). Parsed ASTs are
cached in memory and invalidated automatically on `mtime` change, so repeated reads of an unchanged file are fast.

## Installation

The package is not yet published to PyPI. Install it in editable mode directly from the repository.

### pip

```bash
pip install -e .
```

### uv

```bash
uv pip install -e .
```

## Connecting to opencode / Claude Desktop

After installation the `md-mcp` entry-point script is on your `PATH`. Add it as a local stdio MCP server in your client config.

### opencode (`opencode.json` / `opencode.jsonc`)

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "md-mcp": {
      "type": "local",
      "command": ["md-mcp", "--allow-root", "/your/docs/dir"]
    }
  }
}
```

### Claude Desktop (`claude_desktop_config.json`)

Claude Desktop uses the top-level key `mcpServers`:

```json
{
  "mcpServers": {
    "md-mcp": {
      "command": "md-mcp",
      "args": [],
      "transport": "stdio"
    }
  }
}
```

## Dot-path addressing

Every tool that targets a section takes a `path` argument — a dot-separated string of heading texts from the
document root down to the target section. Given this Markdown file:

```markdown
# My Project

## Installation

### Prerequisites

## Usage
```

The available paths are:

| Section | Path |
|---|---|
| `# My Project` | `My Project` |
| `## Installation` | `My Project.Installation` |
| `### Prerequisites` | `My Project.Installation.Prerequisites` |
| `## Usage` | `My Project.Usage` |

Matching is **case-insensitive**, so `my project.installation` and `My Project.Installation` resolve to the
same section. Ambiguous paths (duplicate heading texts at the same level) resolve to the first match.

## Tool reference

| Tool | Arguments | Returns | Description |
|---|---|---|---|
| `get_index` | `file_path: str` | `dict` | Returns the full section tree of a file as a nested dict with `heading`, `level`, `path`, and `children` fields. |
| `get_section` | `file_path: str`, `path: str`, `depth: int \| None = None` | `str` | Returns the raw Markdown text of the named section. `depth=None` (default): full subtree; `depth=0`: heading + own body only; `depth=N`: heading + N levels of children. |
| `search_sections` | `file_path: str`, `query: str`, `case_sensitive: bool = False` | `list` | Searches all section bodies for lines matching `query` (Python regex). Returns a list of `{"path", "matches": [{"line", "text"}]}` objects in file order. Each section's own body is searched independently — results are never duplicated across parent and child. **Heading text is not searched** — use `get_index` to find terms in headings. |
| `add_section` | `file_path: str`, `heading: str`, `content: str`, `under: str \| None = None`, `before: str \| None = None`, `after: str \| None = None` | `str` | Inserts a new section. `heading` must start with `#`–`######` followed by a space. Placement: `under` (last child), `before` (immediately before), `after` (immediately after including its children), or omit all to append. Returns `"ok"`. |
| `replace_section` | `file_path: str`, `path: str`, `new_content: str` | `str` | Replaces the body of the named section, preserving its heading line. Returns `"ok"`. |
| `patch_section` | `file_path: str`, `path: str`, `new_content: str` | `str` | Returns a unified diff of what `replace_section` would write, without modifying the file. Returns an empty string if there are no changes. |
| `delete_section` | `file_path: str`, `path: str`, `include_children: bool = True` | `str` | Deletes the named section. With `include_children=True` (default) removes the heading, its body, and all child sections; with `False` removes only the heading and its direct body, promoting children. Returns `"ok"`. |

## Examples

A short worked session against a file `docs/guide.md` whose top-level heading is `User Guide`:

**1. Inspect the structure**

```
get_index("docs/guide.md")
```

Returns a nested tree:

```json
{
  "sections": [
    {
      "heading": "User Guide",
      "level": 1,
      "path": "User Guide",
      "children": [
        {
          "heading": "Getting Started",
          "level": 2,
          "path": "User Guide.Getting Started",
          "children": []
        },
        {
          "heading": "Configuration",
          "level": 2,
          "path": "User Guide.Configuration",
          "children": []
        }
      ]
    }
  ]
}
```

**2. Read a section**

```
get_section("docs/guide.md", "User Guide.Getting Started")
```

Returns the raw Markdown text of that section (heading line + body).

**3. Preview a change**

```
patch_section("docs/guide.md", "User Guide.Configuration", "Set `debug: true` in `config.yaml`.")
```

Returns a unified diff showing exactly what would change — nothing is written yet.

**4. Apply the change**

```
replace_section("docs/guide.md", "User Guide.Configuration", "Set `debug: true` in `config.yaml`.")
```

Returns `"ok"`. The file is updated; the heading line is preserved unchanged.

**5. Add a new section**

```
add_section("docs/guide.md", "## Troubleshooting", "See the FAQ.", after="User Guide.Configuration")
```

Returns `"ok"`. The new `## Troubleshooting` section is inserted immediately after `## Configuration`.

**6. Find sections mentioning a term**

```
search_sections("docs/guide.md", "debug")
```

Returns:

```json
[
  {
    "path": "User Guide.Configuration",
    "matches": [
      {"line": 18, "text": "Set `debug: true` in `config.yaml`."}
    ]
  }
]
```

## Development

**Requirements:** Python 3.11+

Install the package with dev dependencies:

```bash
pip install -e ".[dev]"
```

Run the test suite:

```bash
pytest
```

Set up and run pre-commit hooks (ruff + mypy):

```bash
pre-commit install
pre-commit run --all-files
```
