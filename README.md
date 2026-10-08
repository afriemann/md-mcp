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
| `search_sections` | `file_path: str`, `query: str`, `case_sensitive: bool = False`, `scope: str = "body"` | `list` | Searches lines matching `query` (Python regex). `scope`: `"body"` (default — section bodies, unchanged behaviour), `"headings"` (heading text only) or `"both"`. Returns a list of `{"path", "matches": [{"line", "text"}]}` objects in file order; for a heading match `line` is the heading line and `text` the heading text. Each section's own body is searched independently — results are never duplicated across parent and child. Frontmatter lines are reported under path `frontmatter` when bodies are searched. |
| `search_files` | `directory: str`, `glob: str`, `query: str`, `scope: str = "body"`, `case_sensitive: bool = False`, `limit: int = 100`, `max_file_bytes: int = 1048576` | `dict` | Runs `search_sections` over every file matching `glob` (relative to `directory`, e.g. `**/*.md`). Returns `{"matches": [{"file_path", "path", "line", "text"}], "skipped", "truncated", "limit"}`. `glob` must be relative with no `..`. Unreadable, non-UTF-8, oversized (> `max_file_bytes`) and symlink-escaping files are skipped and counted in `skipped`; `truncated` is true when more than `limit` (max 1000) matches exist. Match `text` is cut to 300 characters. |
| `add_section` | `file_path: str`, `heading: str`, `content: str`, `under: str \| None = None`, `before: str \| None = None`, `after: str \| None = None` | `str` | Inserts a new section. `heading` must start with `#`–`######` followed by a space. Placement: `under` (last child), `before` (immediately before), `after` (immediately after including its children), or omit all to append. Returns `"ok"`. |
| `replace_section` | `file_path: str`, `path: str`, `new_content: str` | `str` | Replaces the body of the named section, preserving its heading line. `path="frontmatter"` replaces the YAML between the `---` delimiters (delimiters kept; a result that is not a valid YAML mapping is rejected and the file left unchanged). Returns `"ok"`. |
| `replace_in_section` | `file_path: str`, `path: str`, `old: str`, `new: str`, `replace_all: bool = False` | `str` | Replaces the exact string `old` with `new` inside the section's own body (heading line and child sections excluded; `path="frontmatter"` edits the YAML block). Multi-line `old`/`new` may use `\n` on CRLF files. Errors, writing nothing, when `old` is absent, when it matches more than once and `replace_all` is false (the error states the count), or when `old == new`. Bytes outside the replaced text are never changed. Returns the unified diff. |
| `patch_section` | `file_path: str`, `path: str`, `new_content: str` | `str` | Returns a unified diff of what `replace_section` would write (including for `path="frontmatter"`), without modifying the file. Returns an empty string if there are no changes. |
| `delete_section` | `file_path: str`, `path: str`, `include_children: bool = True` | `str` | Deletes the named section. With `include_children=True` (default) removes the heading, its body, and all child sections; with `False` removes only the heading and its direct body, promoting children. `path="frontmatter"` is rejected. Returns `"ok"`. |

## Frontmatter

A file has frontmatter when its first line is exactly `---`, a later line is exactly `---`, **and** the lines between
them are a YAML mapping (`key: value` lines). `{{ ... }}` template actions inside count as scalar values; a block that
fails to parse only because it contains `{{` template syntax (e.g. `{{- if .x }}` around keys) is still frontmatter.
Anything else — such as a document that opens with a horizontal rule and has another one later — is **not** frontmatter
and is parsed as ordinary Markdown, headings included.

`get_index` lists frontmatter as a separate first node `{"heading": "frontmatter", "level": 0, "path": "frontmatter", "children": []}`;
it is never parsed as a heading and the body after it is indexed normally. The path `frontmatter` is reserved: when a file
has a frontmatter block it takes precedence over a top-level heading literally named "frontmatter". `get_section`,
`replace_section`, `patch_section`, `replace_in_section` and `search_sections` accept it; `add_section` and `delete_section`
reject it. An edit must leave a valid YAML mapping (templates as scalars) or it is rejected and the file stays unchanged;
a block that already could not be parsed because of template syntax is not re-validated.

## Template files and byte fidelity

Files with `{{ ... }}` template actions (e.g. `*.md.tmpl`) are supported: `#` inside a fenced code block or inside a
multi-line template action is text, not a heading. A template action may span at most 20 lines and never a blank line;
an unbalanced `{{` is plain text. Every write tool (`replace_section`, `replace_in_section`, `add_section`,
`delete_section`) preserves all bytes outside the edited span: CRLF, mixed and lone-CR line endings, trailing blank
lines, and a missing final newline. Lines created by an edit use the file's dominant line ending. Lines are split on `\n`
only, so form feed, U+2028 and similar characters stay inside their line.

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
