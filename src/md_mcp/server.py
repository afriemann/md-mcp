"""md-mcp MCP server — Markdown section editor."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from md_mcp.document import MarkdownDocument

mcp = FastMCP("md-mcp")

# ---------------------------------------------------------------------------
# Path guard
# ---------------------------------------------------------------------------

_allowed_roots: list[Path] | None = None


def _check_path(file_path: str) -> Path:
    """Resolve *file_path* and verify it is within an allowed root.

    If ``_allowed_roots`` is ``None`` (unrestricted mode), only resolves the
    path.  Otherwise raises ``PermissionError`` when the resolved path is not
    relative to at least one allowed root.
    """
    resolved = Path(file_path).expanduser().resolve()
    if _allowed_roots is not None:
        if not any(resolved.is_relative_to(root) for root in _allowed_roots):
            raise PermissionError(f"path not under any allowed root: {file_path}")
    return resolved


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def get_index(file_path: str) -> dict[str, Any]:
    """Return the section index of a Markdown file as a nested tree.

    Each node: {"heading": str, "level": int, "path": str, "children": [...]}
    The "path" field is the dot-separated address used by all other tools.
    Literal dots in heading text are represented as \\. in path strings.
    """
    try:
        doc = MarkdownDocument(str(_check_path(file_path)))
        return doc.get_index()
    except PermissionError:
        return {"error": f"access denied: {file_path}"}
    except FileNotFoundError:
        return {"error": f"file not found: {file_path}"}
    except (UnicodeDecodeError, UnicodeError):
        return {"error": f"file is not valid UTF-8: {file_path}"}
    except OSError as e:
        return {"error": f"I/O error: {e.strerror}"}


@mcp.tool()
def get_section(
    file_path: str,
    path: str,
    depth: int | None = None,
) -> str:
    """Return the heading line(s) and body of the section at `path`.

    `path` is a dot-separated heading path, e.g. "My README.Installation.Prerequisites".
    Matching is case-insensitive. Returns the raw Markdown text of the section.

    `depth` controls how many levels of child sections are included:
      - None (default): return the section and all descendants
      - 0: return the heading and its own body only (no child sections)
      - 1: heading + own body + immediate children
      - 2: heading + own body + children + grandchildren
      etc.

    Raises an error string if the path does not exist.
    """
    try:
        doc = MarkdownDocument(str(_check_path(file_path)))
        return doc.get_section(path, depth=depth)
    except PermissionError:
        return f"Error: access denied: {file_path}"
    except FileNotFoundError:
        return f"Error: file not found: {file_path}"
    except KeyError as e:
        return f"Error: {e}"
    except ValueError as e:
        return f"Error: {e}"
    except (UnicodeDecodeError, UnicodeError):
        return f"Error: file is not valid UTF-8: {file_path}"
    except OSError as e:
        return f"Error: I/O error: {e.strerror}"


@mcp.tool()
def search_sections(
    file_path: str,
    query: str,
    case_sensitive: bool = False,
) -> list[dict[str, Any]]:
    """Search all section bodies for lines matching `query` (regex).

    Returns a list of match objects — one per section that contains at least
    one hit — in file order:

        [
          {
            "path": "Root.Child",
            "matches": [
              {"line": 12, "text": "...the matching line text..."},
              ...
            ]
          },
          ...
        ]

    `line` is the 1-based line number within the file.
    Only each section's own body is searched (not its children), so results
    are never duplicated across parent and child sections.
    `query` is a Python regex; raises an error string if the pattern is invalid.
    """
    import re as _re

    try:
        doc = MarkdownDocument(str(_check_path(file_path)))
        return doc.search_sections(query, case_sensitive=case_sensitive)
    except FileNotFoundError:
        return [{"error": f"file not found: {file_path}"}]
    except PermissionError:
        return [{"error": f"access denied: {file_path}"}]
    except (UnicodeDecodeError, UnicodeError):
        return [{"error": f"file is not valid UTF-8: {file_path}"}]
    except OSError as e:
        return [{"error": f"I/O error: {e.strerror}"}]
    except _re.error as e:
        return [{"error": f"invalid regex: {e}"}]


@mcp.tool()
def add_section(
    file_path: str,
    heading: str,
    content: str,
    under: str | None = None,
    before: str | None = None,
    after: str | None = None,
) -> str:
    """Insert a new section into a Markdown file.

    `heading` must start with 1–6 '#' characters followed by a space, e.g. "## New Section".
    `content` is the body text (no heading line).
    Placement: exactly one of `under`, `before`, `after` may be set, or all None to append.
      - `under`: insert as the last child of the named section
      - `before`: insert immediately before the named section
      - `after`: insert immediately after the named section (and all its children)
    Returns "ok" on success.
    """
    try:
        doc = MarkdownDocument(str(_check_path(file_path)))
        doc.add_section(heading, content, under=under, before=before, after=after)
        return "ok"
    except PermissionError:
        return f"Error: access denied: {file_path}"
    except FileNotFoundError:
        return f"Error: file not found: {file_path}"
    except KeyError as e:
        return f"Error: {e}"
    except ValueError as e:
        return f"Error: {e}"
    except (UnicodeDecodeError, UnicodeError):
        return f"Error: file is not valid UTF-8: {file_path}"
    except OSError as e:
        return f"Error: I/O error: {e.strerror}"


@mcp.tool()
def replace_section(file_path: str, path: str, new_content: str) -> str:
    """Replace the body of a section, preserving its heading line.

    The heading line is kept unchanged; only the body text is replaced.
    Returns "ok" on success.
    """
    try:
        doc = MarkdownDocument(str(_check_path(file_path)))
        doc.replace_section(path, new_content)
        return "ok"
    except PermissionError:
        return f"Error: access denied: {file_path}"
    except FileNotFoundError:
        return f"Error: file not found: {file_path}"
    except KeyError as e:
        return f"Error: {e}"
    except ValueError as e:
        return f"Error: {e}"
    except (UnicodeDecodeError, UnicodeError):
        return f"Error: file is not valid UTF-8: {file_path}"
    except OSError as e:
        return f"Error: I/O error: {e.strerror}"


@mcp.tool()
def patch_section(file_path: str, path: str, new_content: str) -> str:
    """Return a unified diff of what replace_section would do, without writing.

    Useful for previewing changes before committing them.
    Returns the unified diff as a string (empty string if no changes).
    """
    try:
        doc = MarkdownDocument(str(_check_path(file_path)))
        return doc.patch_section(path, new_content)
    except PermissionError:
        return f"Error: access denied: {file_path}"
    except FileNotFoundError:
        return f"Error: file not found: {file_path}"
    except KeyError as e:
        return f"Error: {e}"
    except ValueError as e:
        return f"Error: {e}"
    except (UnicodeDecodeError, UnicodeError):
        return f"Error: file is not valid UTF-8: {file_path}"
    except OSError as e:
        return f"Error: I/O error: {e.strerror}"


@mcp.tool()
def delete_section(
    file_path: str,
    path: str,
    include_children: bool = True,
) -> str:
    """Delete a section from a Markdown file.

    With include_children=True (default): deletes the heading, its body, and all child sections.
    With include_children=False: deletes only the heading and its own body; child sections are promoted.
    Returns "ok" on success.
    """
    try:
        doc = MarkdownDocument(str(_check_path(file_path)))
        doc.delete_section(path, include_children=include_children)
        return "ok"
    except PermissionError:
        return f"Error: access denied: {file_path}"
    except FileNotFoundError:
        return f"Error: file not found: {file_path}"
    except KeyError as e:
        return f"Error: {e}"
    except ValueError as e:
        return f"Error: {e}"
    except (UnicodeDecodeError, UnicodeError):
        return f"Error: file is not valid UTF-8: {file_path}"
    except OSError as e:
        return f"Error: I/O error: {e.strerror}"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Run the md-mcp MCP server over stdio."""
    global _allowed_roots  # noqa: PLW0603

    parser = argparse.ArgumentParser(
        description="md-mcp: MCP server for Markdown section editing"
    )
    parser.add_argument(
        "--allow-root",
        metavar="PATH",
        action="append",
        dest="allow_roots",
        default=None,
        help=(
            "Restrict file access to this directory (may be repeated). "
            "If not set, all paths are accessible (unrestricted mode)."
        ),
    )
    args = parser.parse_args()

    if args.allow_roots is None:
        print(
            "WARNING: md-mcp is running in unrestricted mode — "
            "any readable/writable file is accessible. "
            "Pass --allow-root <path> to restrict access.",
            file=sys.stderr,
        )
        _allowed_roots = None
    else:
        _allowed_roots = [Path(p).expanduser().resolve() for p in args.allow_roots]

    mcp.run(transport="stdio")
