"""MarkdownDocument: surgical read/write access to Markdown sections.

.. note::
    Concurrent writes to the same file from different threads are not atomic —
    use external file locking if strict ordering is required.
"""

from __future__ import annotations

import difflib
import os
import re
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any

from mistletoe import Document as MistletoeDocument
from mistletoe.block_token import Heading, SetextHeading
from mistletoe.span_token import RawText

# ---------------------------------------------------------------------------
# Module-level AST cache: {filepath_str: (mtime_float, parsed_data)}
# ---------------------------------------------------------------------------
_CACHE_MAX = 256
_CACHE: OrderedDict[str, tuple[float, "_ParsedDocument"]] = OrderedDict()
_CACHE_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _is_heading(token: Any) -> bool:
    """Return True for ATX or setext heading tokens."""
    return isinstance(token, (Heading, SetextHeading))


def _heading_level(token: Any) -> int:
    return int(token.level)


def _heading_text(token: Any) -> str:
    """Extract plain text from a heading token (strips inline markup)."""

    def _collect(tok: Any) -> str:
        if isinstance(tok, RawText):
            return tok.content
        children = getattr(tok, "_children", None) or getattr(tok, "children", None)
        if children:
            return "".join(_collect(c) for c in children)
        return ""

    children = getattr(token, "_children", None) or getattr(token, "children", None)
    if not children:
        return ""
    return "".join(_collect(c) for c in children).strip()


def _heading_start_line(token: Any) -> int:
    """Return 0-indexed start line of the heading (text line)."""
    return token.line_number - 1


def _heading_end_line(token: Any) -> int:
    """Return 0-indexed exclusive end line of the heading block.

    For ATX headings (``# foo``): occupies one line.
    For setext headings (underlined): two lines (text + underline).
    """
    start = _heading_start_line(token)
    if isinstance(token, SetextHeading):
        return start + 2
    return start + 1


# ---------------------------------------------------------------------------
# Parsed document representation
# ---------------------------------------------------------------------------


class _HeadingInfo:
    """Lightweight record for one heading extracted from the token walk."""

    __slots__ = ("level", "text", "start_line", "end_line")

    def __init__(self, level: int, text: str, start_line: int, end_line: int) -> None:
        self.level = level
        self.text = text
        self.start_line = start_line  # 0-indexed, inclusive
        self.end_line = end_line  # 0-indexed, exclusive (past heading markup)


class _ParsedDocument:
    """Cached result of parsing one Markdown file."""

    def __init__(self, headings: list[_HeadingInfo]) -> None:
        self.headings = headings

    @classmethod
    def from_text(cls, text: str) -> "_ParsedDocument":
        doc = MistletoeDocument(text)
        headings: list[_HeadingInfo] = []
        for token in doc.children or []:
            if _is_heading(token):
                headings.append(
                    _HeadingInfo(
                        level=_heading_level(token),
                        text=_heading_text(token),
                        start_line=_heading_start_line(token),
                        end_line=_heading_end_line(token),
                    )
                )
        return cls(headings)


# ---------------------------------------------------------------------------
# Path resolution helpers
# ---------------------------------------------------------------------------


def _normalize_segment(segment: str) -> str:
    """Normalise a single path segment for case-insensitive comparison."""
    return segment.strip().lower()


def _escape_segment(text: str) -> str:
    """Escape literal dots in a heading text for use in a path string.

    A literal ``.`` in heading text is represented as ``\\.`` so it is not
    confused with the path-level separator (``.``).
    """
    return text.replace(".", "\\.")


def _split_path(path: str) -> list[str]:
    """Split a dot-separated path on unescaped dots only.

    Dots preceded by a backslash (``\\.``) are treated as literals and kept
    (with the backslash stripped) in the returned segments.

    Examples::

        >>> _split_path("Root.Section A")
        ['Root', 'Section A']
        >>> _split_path("Root.v1\\\\.2\\\\.3")
        ['Root', 'v1.2.3']
    """
    # Split on dots NOT preceded by a backslash.
    # We use a negative-lookbehind: (?<!\\\\)\\.
    raw_segments = re.split(r"(?<!\\)\.", path)
    # Unescape \\. → . in each segment
    return [seg.replace("\\.", ".") for seg in raw_segments]


def _build_index_tree(headings: list[_HeadingInfo]) -> list[dict[str, Any]]:
    """Build the nested index tree returned by ``get_index``.

    The tree represents all headings as a forest (list of root nodes), where
    each node has ``heading``, ``level``, ``path``, and ``children`` fields.
    """
    roots: list[dict[str, Any]] = []
    # Stack of (node_dict, path_prefix)
    stack: list[tuple[dict[str, Any], str]] = []

    for h in headings:
        node: dict[str, Any] = {
            "heading": h.text,
            "level": h.level,
            "path": "",
            "children": [],
        }

        # Pop stack entries at the same or deeper level
        while stack and stack[-1][0]["level"] >= h.level:
            stack.pop()

        if not stack:
            # Top-level node
            node["path"] = _escape_segment(h.text)
            roots.append(node)
        else:
            parent_node, _parent_path = stack[-1]
            node["path"] = parent_node["path"] + "." + _escape_segment(h.text)
            parent_node["children"].append(node)

        stack.append((node, node["path"]))

    return roots


def _resolve_path(headings: list[_HeadingInfo], path: str) -> int:
    """Resolve a dot-separated heading path to an index into ``headings``.

    Returns the 0-based index of the matched heading.
    Raises ``KeyError`` if not found.
    Ambiguous paths (multiple same-text siblings) resolve to the first match.

    Literal dots in heading text are represented as ``\\.`` in the path string
    (e.g. a heading ``v1.2.3`` under ``Root`` has path ``Root.v1\\.2\\.3``).
    """
    segments = [_normalize_segment(s) for s in _split_path(path)]
    if not segments or any(s == "" for s in segments):
        raise KeyError(f"Invalid path: {path!r}")

    # We walk the headings list maintaining a "current parent level".
    # The first segment must match a top-level heading (level 1 … N with no
    # ancestor at a lower level that has been entered).
    # Each subsequent segment must be a child of the previously matched heading.

    # Strategy: iterate segments, narrow to candidates at each step.
    seg_idx = 0
    # Start: candidates are all headings that could be roots (no constraint).
    # After matching segment[0], we note the level matched and enter children.

    matched_idx: int = -1
    # search_from is the index in headings where we start looking for this segment
    search_from = 0
    # search_below_level: None means top-level (no constraint); int means we
    # must be a child of the previously matched heading.
    parent_level: int | None = None
    parent_idx: int | None = None

    for seg in segments:
        found = False
        for i in range(search_from, len(headings)):
            h = headings[i]
            ht = _normalize_segment(h.text)

            if parent_level is None:
                # Looking for a root-level segment: accept *any* level, but
                # it must not be "inside" another heading of a lower level
                # that we haven't matched yet. Because the tree is a flat list,
                # a root segment is the first heading in the file that matches.
                # Actually, per the spec: the first path segment is "the root
                # document heading (the first # … heading)."
                # We treat the first segment as matching the first heading
                # whose normalised text equals the segment, with no level
                # constraint (it could be H1 or H2 etc.).
                if ht == seg:
                    matched_idx = i
                    parent_level = h.level
                    parent_idx = i
                    search_from = i + 1
                    found = True
                    break
            else:
                # If we've gone past a heading whose level is ≤ parent_level,
                # we've left the parent's scope → stop searching.
                assert parent_idx is not None
                if i > parent_idx and h.level <= parent_level:
                    break
                # Must be a direct child: level == parent_level + 1 OR any
                # level that is > parent_level (the spec doesn't mandate
                # direct children only — a path like "Root.Sub" should match
                # ## Sub under # Root regardless of intermediate levels).
                # Per spec: "dot-separated heading text" — we match by text at
                # any child level, not necessarily level+1.
                if h.level > parent_level and ht == seg:
                    matched_idx = i
                    parent_level = h.level
                    parent_idx = i
                    search_from = i + 1
                    found = True
                    break

        if not found:
            raise KeyError(
                f"Path segment {seg!r} not found in {path!r}. "
                f"No matching heading after resolving {segments[:seg_idx]!r}."
            )
        seg_idx += 1

    return matched_idx


def _section_lines(
    headings: list[_HeadingInfo],
    idx: int,
    lines: list[str],
    *,
    include_children: bool,
) -> tuple[int, int]:
    """Return the (start, end) 0-indexed line range (exclusive end) for the
    section at ``headings[idx]``.

    ``start`` is the heading's start line.
    ``end`` is the line just before the next heading that terminates this section.

    With ``include_children=True``: stop at next heading of *same or higher*
    level (lower '#' count).
    With ``include_children=False``: stop at next heading of *any* level.
    """
    h = headings[idx]
    start = h.start_line

    # Find the end: scan subsequent headings
    end = len(lines)
    for j in range(idx + 1, len(headings)):
        next_h = headings[j]
        if include_children:
            # Stop at same or higher level (lower or equal '#' count)
            if next_h.level <= h.level:
                end = next_h.start_line
                break
        else:
            # Stop at any heading
            end = next_h.start_line
            break

    return start, end


# ---------------------------------------------------------------------------
# Public class
# ---------------------------------------------------------------------------


class MarkdownDocument:
    """Surgical read/write access to a Markdown file's sections."""

    def __init__(self, filepath: str | Path) -> None:
        self._path = Path(filepath).resolve()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _read_text(self) -> str:
        return self._path.read_text(encoding="utf-8")

    def _read_lines(self) -> list[str]:
        return self._path.read_text(encoding="utf-8").splitlines()

    def _parsed(self) -> _ParsedDocument:
        """Return cached parsed document, refreshing on mtime change."""
        path_str = str(self._path)
        mtime = os.stat(self._path).st_mtime
        with _CACHE_LOCK:
            if path_str in _CACHE and _CACHE[path_str][0] == mtime:
                return _CACHE[path_str][1]
        text = self._path.read_text(encoding="utf-8")
        parsed = _ParsedDocument.from_text(text)
        with _CACHE_LOCK:
            if len(_CACHE) >= _CACHE_MAX:
                _CACHE.popitem(last=False)
            _CACHE[path_str] = (mtime, parsed)
        return parsed

    def _invalidate_cache(self) -> None:
        with _CACHE_LOCK:
            _CACHE.pop(str(self._path), None)

    def _write_lines(self, lines: list[str]) -> None:
        content = "\n".join(lines)
        # Preserve trailing newline if original had it
        if content and not content.endswith("\n"):
            content += "\n"
        self._path.write_text(content, encoding="utf-8")
        self._invalidate_cache()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_index(self) -> dict[str, Any]:
        """Return a nested tree of headings.

        Returns a dict with a single key ``"sections"`` whose value is a list
        of root-level section nodes.  Each node has:

        * ``heading`` (str): heading text
        * ``level`` (int): heading level (1–6)
        * ``path`` (str): dot-separated path from root to this node
        * ``children`` (list): child nodes (same structure)
        """
        parsed = self._parsed()
        return {"sections": _build_index_tree(parsed.headings)}

    def get_section(self, path: str, *, include_children: bool = True) -> str:
        """Return the heading line(s) + body text of the named section.

        ``path`` is a dot-separated heading path.  Literal dots in heading
        text are represented as ``\\.`` (e.g. ``"Root.v1\\.2\\.3"``).
        Raises ``KeyError`` if the path does not resolve.
        """
        parsed = self._parsed()
        idx = _resolve_path(parsed.headings, path)
        lines = self._read_lines()
        start, end = _section_lines(
            parsed.headings, idx, lines, include_children=include_children
        )
        return "\n".join(lines[start:end])

    def add_section(
        self,
        heading: str,
        content: str,
        *,
        under: str | None = None,
        before: str | None = None,
        after: str | None = None,
    ) -> None:
        """Insert a new section into the document and write to file.

        Exactly one of ``under``, ``before``, ``after`` may be set, or all
        ``None`` to append at end of document.

        ``heading`` must start with one or more ``#`` characters followed by
        a space, e.g. ``"## New Section"``.

        The path arguments (``under``, ``before``, ``after``) use
        dot-separated heading paths.  Literal dots in heading text are
        represented as ``\\.`` (e.g. ``"Root.v1\\.2\\.3"``).
        """
        if not re.match(r"^#{1,6} ", heading):
            raise ValueError(
                f"heading must start with 1–6 '#' characters followed by a space; "
                f"got {heading!r}"
            )

        anchors = [a for a in (under, before, after) if a is not None]
        if len(anchors) > 1:
            raise ValueError("At most one of under/before/after may be specified.")

        # Build the new block to insert (heading line + optional body)
        block_lines = [heading]
        if content:
            body = content.rstrip("\n")
            block_lines.append("")  # blank line after heading
            block_lines.extend(body.splitlines())
        # Ensure trailing blank line for separation
        block_lines.append("")

        # Re-read file right before writing to avoid races
        lines = self._read_lines()
        parsed = _ParsedDocument.from_text("\n".join(lines))
        headings = parsed.headings

        if under is None and before is None and after is None:
            # Append at end of document
            # Ensure at least one blank line separator from existing content
            insert_at = len(lines)
            if lines and lines[-1].strip() != "":
                lines.append("")
            lines.extend(block_lines)
        elif before is not None:
            idx = _resolve_path(headings, before)
            h = headings[idx]
            insert_at = h.start_line
            # Ensure blank line before the new block if not at start
            if insert_at > 0 and lines[insert_at - 1].strip() != "":
                block_lines = [""] + block_lines
            lines[insert_at:insert_at] = block_lines
        elif after is not None:
            idx = _resolve_path(headings, after)
            # Insert after the entire section (including children)
            _, section_end = _section_lines(headings, idx, lines, include_children=True)
            insert_at = section_end
            # Trim trailing blank lines from the section to avoid double-blanks
            while insert_at > 0 and lines[insert_at - 1].strip() == "":
                insert_at -= 1
            lines[insert_at:insert_at] = [""] + block_lines
        else:
            # under: insert as last child of the target section
            assert under is not None
            idx = _resolve_path(headings, under)
            _, section_end = _section_lines(headings, idx, lines, include_children=True)
            insert_at = section_end
            while insert_at > 0 and lines[insert_at - 1].strip() == "":
                insert_at -= 1
            lines[insert_at:insert_at] = [""] + block_lines

        self._write_lines(lines)

    def replace_section(self, path: str, new_content: str) -> None:
        """Replace the body of a section, preserving the heading line.

        ``path`` is a dot-separated heading path.  Literal dots in heading
        text are represented as ``\\.`` (e.g. ``"Root.v1\\.2\\.3"``).
        Writes to file and invalidates the cache.
        Raises ``KeyError`` if the path does not resolve.
        """
        # Re-read right before write
        lines = self._read_lines()
        parsed = _ParsedDocument.from_text("\n".join(lines))
        idx = _resolve_path(parsed.headings, path)
        h = parsed.headings[idx]

        start, end = _section_lines(parsed.headings, idx, lines, include_children=True)

        # heading_end_line is where the body begins (after heading markup)
        heading_end = h.end_line  # exclusive, 0-indexed
        heading_lines = lines[start:heading_end]

        # Build new body lines
        new_body = new_content.rstrip("\n")
        if new_body:
            body_lines = [""] + new_body.splitlines()
        else:
            body_lines = []

        # Preserve trailing blank line(s) at end of section
        trailing: list[str] = []
        j = end - 1
        while j >= heading_end and j < len(lines) and lines[j].strip() == "":
            trailing.insert(0, lines[j])
            j -= 1
        if not trailing:
            trailing = [""]

        new_section = heading_lines + body_lines + trailing
        lines[start:end] = new_section
        self._write_lines(lines)

    def patch_section(self, path: str, new_content: str) -> str:
        """Return a unified diff of what ``replace_section`` would do.

        ``path`` is a dot-separated heading path.  Literal dots in heading
        text are represented as ``\\.`` (e.g. ``"Root.v1\\.2\\.3"``).
        Does NOT write to file.
        """
        # Get current content
        original_text = self._read_text()
        original_lines = original_text.splitlines(keepends=True)

        # Simulate replace_section by working on the current state
        lines = self._read_lines()
        parsed = _ParsedDocument.from_text("\n".join(lines))
        idx = _resolve_path(parsed.headings, path)
        h = parsed.headings[idx]
        start, end = _section_lines(parsed.headings, idx, lines, include_children=True)

        heading_end = h.end_line
        heading_lines = lines[start:heading_end]

        new_body = new_content.rstrip("\n")
        if new_body:
            body_lines = [""] + new_body.splitlines()
        else:
            body_lines = []

        trailing: list[str] = []
        j = end - 1
        while j >= heading_end and j < len(lines) and lines[j].strip() == "":
            trailing.insert(0, lines[j])
            j -= 1
        if not trailing:
            trailing = [""]

        new_section = heading_lines + body_lines + trailing
        new_lines = lines[:start] + new_section + lines[end:]
        new_text = "\n".join(new_lines)
        if new_text and not new_text.endswith("\n"):
            new_text += "\n"
        new_lines_with_endings = new_text.splitlines(keepends=True)

        diff = difflib.unified_diff(
            original_lines,
            new_lines_with_endings,
            fromfile=str(self._path),
            tofile=str(self._path) + " (patched)",
        )
        return "".join(diff)

    def delete_section(self, path: str, *, include_children: bool = True) -> None:
        """Delete a section from the document and write to file.

        ``path`` is a dot-separated heading path.  Literal dots in heading
        text are represented as ``\\.`` (e.g. ``"Root.v1\\.2\\.3"``).
        With ``include_children=True`` (default): delete heading + body +
        all child sections.
        With ``include_children=False``: delete the heading + its own body
        only; child sections are promoted (their headings remain in place).
        Consecutive blank lines at the deletion point are collapsed to a
        single blank line.
        Raises ``KeyError`` if the path does not resolve.
        """
        lines = self._read_lines()
        parsed = _ParsedDocument.from_text("\n".join(lines))
        idx = _resolve_path(parsed.headings, path)

        start, end = _section_lines(
            parsed.headings, idx, lines, include_children=include_children
        )

        # When not including children, the end is at the first child heading.
        # That child heading starts right at `end`.  We want to delete only
        # the parent heading + its direct body.
        del lines[start:end]

        # Deduplicate consecutive blank lines at the deletion site
        i = max(0, start - 1)
        while i + 1 < len(lines):
            if lines[i].strip() == "" and lines[i + 1].strip() == "":
                del lines[i]
            else:
                i += 1
        self._write_lines(lines)
