"""md-mcp MCP server — Markdown section editor."""

from __future__ import annotations

import argparse
import asyncio
import os
import signal
import sys
from pathlib import Path
from typing import Any

import anyio
from mcp.server.mcpserver.server import MCPServer

from md_mcp.document import MarkdownDocument

mcp = MCPServer("md-mcp")

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
    if _allowed_roots is not None and not any(
        resolved.is_relative_to(root) for root in _allowed_roots
    ):
        raise PermissionError(f"path not under any allowed root: {file_path}")
    return resolved


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def get_index(file_path: str) -> dict[str, Any]:
    """Call this first to discover the section structure of a Markdown file and obtain valid `path` values required by all other tools (get_section, search_sections, add_section, replace_section, patch_section, delete_section).

    Returns a nested tree: {"heading": str, "level": int, "path": str, "children": [...]}.
    `path` is the dot-separated section address used by every other tool in this server.
    Literal dots in heading text are escaped as \\. in path strings.
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
    """Use to read the current content of a section before editing it. Call get_index first to obtain a valid `path`.

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
    except OSError as e:
        return f"Error: I/O error: {e.strerror}"


@mcp.tool()
def search_sections(
    file_path: str,
    query: str,
    case_sensitive: bool = False,
) -> list[dict[str, Any]]:
    """Use to find sections whose body contains a regex pattern. Returns one result object per matching section, with line numbers and matched text.

    NOTE: heading text is NOT searched — only section bodies. To find a section by heading,
    call get_index and scan the returned paths instead.

    `query`: Python regex. `case_sensitive` defaults to False (case-insensitive).

    Each result: {"path": "Root.Child", "matches": [{"line": 12, "text": "..."}]}.
    The "path" in each result is a valid input for get_section, replace_section, patch_section, and delete_section.
    `line` is the 1-based line number within the file.
    Only each section's own body is searched (not its children), so results
    are never duplicated across parent and child sections.
    Raises an error string if the pattern is invalid.
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
    """Use to add a section that does not yet exist. To update an existing section's body, use replace_section instead. Prefer this over a generic file-write tool when the Markdown file has section structure.

    Call get_index first to discover valid `path` values for the placement parameters.

    `heading`: must start with 1–6 '#' characters followed by a space, e.g. "## New Section".
    `content`: body text only — do NOT include the heading line.
    Placement: set exactly one of `under` (as last child), `before`, or `after`; omit all to append at end.
    Values for `under`, `before`, and `after` must come from get_index.
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
    except OSError as e:
        return f"Error: I/O error: {e.strerror}"


@mcp.tool()
def replace_section(file_path: str, path: str, new_content: str) -> str:
    """Use to update the body of an existing section without touching its heading. Prefer this over a generic file-write tool when the Markdown file has section structure.

    Recommended workflow: get_index → (optionally get_section to read current content) → patch_section to preview the diff → replace_section to commit.

    `path`: dot-separated section address obtained from get_index (e.g. "README.Installation").
    `new_content`: replacement body text — do NOT include the heading line.
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
    except OSError as e:
        return f"Error: I/O error: {e.strerror}"


@mcp.tool()
def patch_section(file_path: str, path: str, new_content: str) -> str:
    """Dry-run preview of replace_section — returns a unified diff without writing to the file. Call this before replace_section to confirm the change is correct.

    An empty return string means new_content is identical to the current section body (no change would be made).

    `path`: dot-separated section address from get_index.
    `new_content`: the replacement body text you intend to pass to replace_section.
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
    except OSError as e:
        return f"Error: I/O error: {e.strerror}"


@mcp.tool()
def delete_section(
    file_path: str,
    path: str,
    include_children: bool = True,
) -> str:
    """Use to permanently remove a section. Prefer this over a generic file-write tool when the Markdown file has section structure. To clear a section's body while keeping its heading, use replace_section with empty content instead.

    Call get_index first to obtain a valid `path`.

    `path`: dot-separated section address from get_index.
    `include_children=True` (default): deletes the heading, its body, and all child sections.
    `include_children=False`: deletes only the heading and its own body; child sections are promoted to the parent level.
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
    except OSError as e:
        return f"Error: I/O error: {e.strerror}"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def _run_with_graceful_shutdown() -> None:
    """Run the MCP server with cooperative SIGTERM handling.

    Replaces the default SIGTERM handler (``SIG_DFL`` — immediate C-level kill)
    with anyio's signal receiver.  When SIGTERM arrives:

    1. Cooperative cancellation propagates through ``_mcp_server.run()``,
       so any in-flight tool-call handlers can run their ``finally`` blocks.
    2. A 1-second force-exit watchdog is started via ``asyncio.create_task``.
       This watchdog is *outside* the anyio task group and therefore survives
       scope cancellation.  If the graceful shutdown hangs (because
       ``stdio_server``'s ``stdin_reader`` task is blocked in a worker thread
       waiting for data on the still-open stdin pipe), the watchdog calls
       ``os._exit(0)`` after one second, terminating the process cleanly.
    3. If the process exits normally before the watchdog fires (e.g. stdin EOF
       closes the pipe), the asyncio event loop shuts down and cancels the
       pending watchdog task.

    The normal stdin-EOF shutdown path is preserved: when ``run_stdio_async()``
    returns on its own, the task group exits without the watchdog ever firing.

    Note: ``asyncio.create_task`` and ``asyncio.sleep`` are used intentionally
    (not anyio equivalents) so the watchdog task is scheduled directly on the
    asyncio event loop and survives anyio scope cancellation.  This requires the
    asyncio backend, which is what ``anyio.run()`` uses by default and what
    ``main()`` relies on.
    """
    with anyio.open_signal_receiver(signal.SIGTERM) as sigterm:
        # Signal handler is now installed.  Emit a marker so tests (and
        # operators) can detect reliably when it is safe to send SIGTERM.
        print("SIGTERM-handler-ready", file=sys.stderr, flush=True)
        async with anyio.create_task_group() as tg:

            async def _watch_sigterm() -> None:
                async for _ in sigterm:
                    # Start a force-exit watchdog outside the task group so it
                    # survives scope cancellation.  It gives the cooperative
                    # cancellation path 1 second to complete in-flight handler
                    # ``finally`` blocks, then calls os._exit(0) to break out of
                    # any thread-level hang (e.g. the stdin_reader worker thread
                    # blocked on readline() of an open pipe).
                    # asyncio.create_task (not anyio) is intentional — see docstring.
                    async def _force_exit() -> None:
                        await asyncio.sleep(1.0)
                        os._exit(0)

                    asyncio.create_task(_force_exit())
                    tg.cancel_scope.cancel()
                    return

            tg.start_soon(_watch_sigterm)
            try:
                await mcp.run_stdio_async()
            finally:
                # Cancel _watch_sigterm when run_stdio_async() returns (stdin
                # EOF normal path) so the task group exits without waiting for
                # a signal that will never come.
                tg.cancel_scope.cancel()


def main() -> None:
    """Run the md-mcp MCP server over stdio."""
    global _allowed_roots  # global assignment is intentional — CLI sets allowed roots

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

    anyio.run(_run_with_graceful_shutdown)
