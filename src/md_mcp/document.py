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

from mistletoe.block_token import Document as MistletoeDocument
from mistletoe.block_token import Heading, SetextHeading
from mistletoe.span_token import RawText
import yaml


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


FRONTMATTER_PATH = "frontmatter"
_FRONTMATTER_DELIM = "---"
_TEMPLATE_MAX_LINES = 20  # a {{ ... }} action may span at most this many lines
_TEMPLATE_PLACEHOLDER = "__TEMPLATE__"
_MASKABLE_LINE_RE = re.compile(r"^\s*(?:#|=+\s*$|-+\s*$)")
_FENCE_RE = re.compile(r"^ {0,3}(```|~~~)")
# Characters Python's str.splitlines() (and so mistletoe) treats as line
# breaks besides "\n"; they are neutralised before parsing so that parser line
# numbers always equal "\n"-split line indices.
_EXOTIC_BREAK_RE = re.compile("[\x0b\x0c\x1c-\x1e\x85\u2028\u2029]|\r(?!\n)")


def _template_spans(lines: list[str]) -> list[tuple[int, int, int, int]]:
    """Locate ``{{ ... }}`` template actions as ``(line, col, end_line, end_col)``.

    An action may span several lines but never a blank line or more than
    ``_TEMPLATE_MAX_LINES`` lines; an unbalanced ``{{`` yields no span.
    Lines inside fenced code blocks are skipped.
    """
    spans: list[tuple[int, int, int, int]] = []
    fence: str | None = None
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        fm = _FENCE_RE.match(line)
        if fm:
            marker = fm.group(1)
            if fence is None:
                fence = marker
            elif marker == fence:
                fence = None
            i += 1
            continue
        if fence is not None:
            i += 1
            continue
        col = 0
        while True:
            start = line.find("{{", col)
            if start == -1:
                break
            end = line.find("}}", start + 2)
            end_line = i
            if end == -1:
                j = i + 1
                while j < n and j - i <= _TEMPLATE_MAX_LINES and lines[j].strip():
                    end = lines[j].find("}}")
                    if end != -1:
                        end_line = j
                        break
                    j += 1
            if end == -1:
                col = start + 2
                continue
            spans.append((i, start, end_line, end + 2))
            i = end_line
            line = lines[i]
            col = end + 2
        i += 1
    return spans


def _mask_templates(lines: list[str]) -> list[str]:
    """Replace every template action by a placeholder scalar."""
    out = list(lines)
    for i, start, j, end in reversed(_template_spans(lines)):
        out[i] = out[i][:start] + _TEMPLATE_PLACEHOLDER + out[j][end:]
        del out[i + 1 : j + 1]
    return out


def _yaml_state(body_lines: list[str]) -> tuple[str, str]:
    """Classify a frontmatter body: ``"mapping"``, ``"other"`` or ``"error"``.

    Template actions are replaced by a placeholder scalar first.  The second
    element is the parser's error message for ``"error"``.
    """
    text = "\n".join(_mask_templates([ln.rstrip("\r") for ln in body_lines]))
    try:
        data = yaml.safe_load(text)
    except (yaml.YAMLError, ValueError) as e:
        return "error", str(e)
    return ("mapping" if isinstance(data, dict) else "other"), ""


def _find_frontmatter(lines: list[str]) -> tuple[int, int] | None:
    """Return ``(0, close)`` — 0-indexed line numbers of the opening and
    closing ``---`` delimiters — or ``None`` when the file has no frontmatter.

    Rule: the first line is exactly ``---``, a later line is exactly ``---``,
    and the lines between them are a YAML mapping (template actions count as
    scalars) — or fail to parse only because they contain ``{{`` template
    syntax.  Anything else (e.g. a document that opens with a horizontal rule
    and has another later) is *not* frontmatter and is parsed as Markdown.
    """
    if not lines or lines[0].rstrip("\r") != _FRONTMATTER_DELIM:
        return None
    for i in range(1, len(lines)):
        if lines[i].rstrip("\r") == _FRONTMATTER_DELIM:
            body = lines[1:i]
            state, _ = _yaml_state(body)
            if state == "mapping":
                return 0, i
            if state == "error" and any("{{" in ln for ln in body):
                return 0, i
            return None
    return None


def _is_frontmatter_path(path: str) -> bool:
    return path.strip().lower() == FRONTMATTER_PATH


def _check_frontmatter_edit(old_body: list[str], new_body: list[str]) -> None:
    """Raise ``ValueError`` unless *new_body* is acceptable frontmatter.

    It must be a YAML mapping (template actions count as scalars).  A body
    that could not be parsed before the edit only because of template syntax
    is not re-validated.
    """
    state, err = _yaml_state(new_body)
    if state == "mapping":
        return
    if state == "error":
        if _yaml_state(old_body)[0] == "error" and any("{{" in ln for ln in new_body):
            return
        raise ValueError(f"frontmatter is not valid YAML: {err}")
    raise ValueError("frontmatter must be a YAML mapping (key: value lines)")


def _mask_for_parse(lines: list[str], fm: tuple[int, int] | None) -> str:
    """Build the text handed to the Markdown parser.

    Line numbers are preserved exactly.  Frontmatter lines are blanked so they
    are never parsed as a heading, and continuation lines of multi-line
    ``{{ ... }}`` template actions that could look like a heading or setext
    underline (``#``, ``===``, ``---``) are replaced by plain text.
    """
    masked = list(lines)
    if fm is not None:
        for i in range(fm[1] + 1):
            masked[i] = ""
    for first, _c, last, _e in _template_spans(masked):
        for i in range(first + 1, last + 1):
            if _MASKABLE_LINE_RE.match(masked[i]):
                masked[i] = "x"
    return "\n".join(masked)


class _ParsedDocument:
    """Cached result of parsing one Markdown file."""

    def __init__(
        self,
        headings: list[_HeadingInfo],
        frontmatter: tuple[int, int] | None = None,
    ) -> None:
        self.headings = headings
        # (opening delimiter line, closing delimiter line), 0-indexed, or None
        self.frontmatter = frontmatter

    @classmethod
    def from_text(cls, text: str) -> "_ParsedDocument":
        text = _EXOTIC_BREAK_RE.sub(" ", text.replace("\r\n", "\n"))
        lines = text.split("\n")
        fm = _find_frontmatter(lines)
        doc = MistletoeDocument(_mask_for_parse(lines, fm))
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
        return cls(headings, fm)


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


def _heading_paths(headings: list[_HeadingInfo]) -> list[str]:
    """Return the dot-path of every heading, in heading order."""
    paths: list[str] = []
    stack: list[tuple[int, str]] = []  # (level, path)
    for h in headings:
        while stack and stack[-1][0] >= h.level:
            stack.pop()
        seg = _escape_segment(h.text)
        path = f"{stack[-1][1]}.{seg}" if stack else seg
        paths.append(path)
        stack.append((h.level, path))
    return paths


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
    depth: int | None,
) -> tuple[int, int]:
    """Return the (start, end) 0-indexed line range (exclusive end) for the
    section at ``headings[idx]``.

    ``start`` is the heading's start line.
    ``end`` is the line just before the next heading that terminates this section.

    ``depth=None``: stop at next heading of *same or higher* level (i.e. lower
    or equal ``#`` count) — returns heading + body + all descendants.
    ``depth=0``: stop at next heading of *any* level — returns heading + own
    body only, no child sections.
    ``depth=N`` (N ≥ 1): span from heading start to the end of the deepest
    allowed descendant (levels ``target_level+1`` … ``target_level+N``); same
    end-boundary as ``depth=None`` (stop at same-or-higher level).  Headings
    deeper than ``target_level+N`` are filtered out in ``_section_text``.
    """
    h = headings[idx]
    start = h.start_line

    # Find the end: scan subsequent headings
    end = len(lines)
    for j in range(idx + 1, len(headings)):
        next_h = headings[j]
        if depth is None or depth >= 1:
            # Stop at same or higher level (lower or equal '#' count)
            if next_h.level <= h.level:
                end = next_h.start_line
                break
        else:
            # depth == 0: stop at any heading
            end = next_h.start_line
            break

    return start, end


def _section_text(
    headings: list[_HeadingInfo],
    idx: int,
    lines: list[str],
    *,
    depth: int | None,
) -> str:
    """Return the text of the section, applying depth filtering.

    For ``depth=None`` or ``depth=0``, delegates to ``_section_lines`` and
    returns a simple slice.  For ``depth >= 1``, excludes lines belonging to
    headings deeper than ``target_level + depth``.
    """
    start, end = _section_lines(headings, idx, lines, depth=depth)
    if depth is None or depth == 0:
        return "\n".join(lines[start:end])

    # depth >= 1: filter out sub-sections deeper than target + depth
    target_level = headings[idx].level
    max_level = target_level + depth

    # Walk through the line range, skipping blocks owned by too-deep headings.
    # Build an exclusion set: collect start..end ranges for headings whose
    # level > max_level.
    excluded_ranges: list[tuple[int, int]] = []
    j = idx + 1
    while j < len(headings) and headings[j].start_line < end:
        hj = headings[j]
        if hj.level > max_level:
            # Find the end of this too-deep block: next heading at any level
            # that is ≤ max_level (i.e. back within the allowed range) or
            # the overall section end.
            block_start = hj.start_line
            block_end = end
            k = j + 1
            while k < len(headings) and headings[k].start_line < end:
                if headings[k].level <= max_level:
                    block_end = headings[k].start_line
                    break
                k += 1
            excluded_ranges.append((block_start, block_end))
            # Skip ahead past all headings in this excluded block
            j = k
        else:
            j += 1

    if not excluded_ranges:
        return "\n".join(lines[start:end])

    # Build the result by including only non-excluded ranges
    result_lines: list[str] = []
    pos = start
    for ex_start, ex_end in excluded_ranges:
        result_lines.extend(lines[pos:ex_start])
        pos = ex_end
    result_lines.extend(lines[pos:end])

    # Strip trailing blank lines introduced by exclusions
    while result_lines and result_lines[-1].strip() == "":
        result_lines.pop()

    return "\n".join(result_lines)


# ---------------------------------------------------------------------------
# Public class
# ---------------------------------------------------------------------------

_SCOPES = frozenset({"body", "headings", "both"})
_HEADING_LINE_RE = re.compile(r"^#{1,6}(?:\s|$)")


def _split_lines(text: str) -> list[str]:
    """Split on ``\\n`` only; a trailing newline does not yield an empty line."""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def _nl(items: list[str], cr: str) -> list[str]:
    """Give newly created lines the file's line-ending suffix (``cr``)."""
    return [x + cr for x in items]


def _dominant_cr(lines: list[str]) -> str:
    """``"\\r"`` when most lines of the file end in CRLF, else ``""``."""
    crlf = sum(1 for ln in lines if ln.endswith("\r"))
    return "\r" if lines and crlf * 2 > len(lines) else ""


def _replace_frontmatter(
    lines: list[str], fm: tuple[int, int], new_content: str, cr: str
) -> list[str]:
    """Return *lines* with the frontmatter body replaced; delimiters kept.

    Raises ``ValueError`` if the new body is not a valid YAML mapping.
    """
    body = new_content.replace("\r\n", "\n").rstrip("\n")
    new_body = body.split("\n") if body else []
    _check_frontmatter_edit(lines[fm[0] + 1 : fm[1]], new_body)
    return lines[: fm[0] + 1] + _nl(new_body, cr) + lines[fm[1] :]


def _strip_leading_heading(new_content: str) -> str:
    """Strip a leading Markdown heading line from *new_content*, if present.

    When an agent passes replacement text that starts with the section heading
    (e.g. ``"## My Section\\nNew body"``), ``replace_section`` and
    ``patch_section`` would otherwise insert a duplicate heading because they
    already preserve the existing one.  This helper removes that first line so
    the result is identical to passing body-only content.

    A blank line immediately following the stripped heading is also removed so
    the body content starts cleanly.
    """
    if not new_content:
        return new_content
    first_newline = new_content.find("\n")
    if first_newline == -1:
        # Single line — strip it if it's a heading, leaving an empty body
        return "" if _HEADING_LINE_RE.match(new_content) else new_content
    first_line = new_content[:first_newline]
    if not _HEADING_LINE_RE.match(first_line):
        return new_content
    remainder = new_content[first_newline + 1 :]
    # Also strip one leading blank line that often follows a heading
    if remainder.startswith("\n"):
        remainder = remainder[1:]
    return remainder


def _new_content_has_child_headings(new_content: str) -> bool:
    """Return True if *new_content* contains any Markdown heading lines.

    Used to decide whether ``replace_section`` / ``patch_section`` must replace
    the full section span (heading + body + children) rather than only the own
    body.  Called after ``_strip_leading_heading`` has already removed the
    section's own heading line, so any remaining heading belongs to a child.

    Lines inside fenced code blocks and inside multi-line ``{{ ... }}``
    template actions are text, not headings.
    """
    lines = new_content.replace("\r\n", "\n").split("\n")
    for first, _c, last, _e in _template_spans(lines):
        for i in range(first + 1, last + 1):
            lines[i] = "x"
    fence: str | None = None
    for line in lines:
        stripped = line.lstrip()
        marker = stripped[:3]
        if marker in ("```", "~~~") and len(line) - len(stripped) < 4:
            if fence is None:
                fence = marker
            elif marker == fence:
                fence = None
            continue
        if fence is None and _HEADING_LINE_RE.match(line):
            return True
    return False


def _peek_html_comment_backward(
    lines: list[str],
    j: int,
    heading_end: int,
) -> tuple[int, list[str]] | None:
    """Try to read an HTML comment block whose last line is ``lines[j]``.

    Handles both single-line (``<!-- … -->``) and multi-line comments.

    Returns ``(new_j, comment_lines)`` where *new_j* is the index immediately
    before the comment block, or ``None`` if ``lines[j]`` is not the end of an
    HTML comment.
    """
    stripped = lines[j].strip()

    # Single-line: starts with <!-- and ends with --> on the same line.
    if stripped.startswith("<!--") and stripped.endswith("-->"):
        return j - 1, [lines[j]]

    # Multi-line end: ends with --> but the opening <!-- is on an earlier line.
    if stripped.endswith("-->"):
        comment_lines: list[str] = [lines[j]]
        k = j - 1
        while k >= heading_end:
            comment_lines.insert(0, lines[k])
            if lines[k].strip().startswith("<!--"):
                return k - 1, comment_lines
            k -= 1
        # Reached heading_end without finding the opening <!-- — not a valid
        # comment block; do not capture.

    return None


def _collect_trailing_separator(
    lines: list[str],
    own_body_end: int,
    heading_end: int,
) -> list[str]:
    """Return the separator lines at the tail of a section's line range.

    Captures blank lines and, **only when the section is followed by another
    heading** (``own_body_end < len(lines)``), single- or multi-line HTML
    comment blocks.  These separator lines are preserved verbatim when a
    section is replaced so that markers such as ``<!-- BEGIN_TF_DOCS -->``
    are not silently dropped.

    When the section reaches end-of-file (``own_body_end == len(lines)``),
    HTML comments are not captured — they are part of the section body and
    the caller may legitimately replace them.
    """
    has_next_section = own_body_end < len(lines)
    natural_sep: list[str] = []
    j = own_body_end - 1
    while j >= heading_end:
        line = lines[j]
        if line.strip() == "":
            natural_sep.insert(0, line)
            j -= 1
            continue
        if has_next_section:
            result = _peek_html_comment_backward(lines, j, heading_end)
            if result is not None:
                new_j, comment_lines = result
                natural_sep = comment_lines + natural_sep
                j = new_j
                continue
        break
    return natural_sep


def _strip_separator_from_tail(
    raw_lines: list[str],
    natural_sep: list[str],
) -> list[str]:
    """Remove separator lines from the tail of *raw_lines* in-place.

    When an agent passes back content it previously read via ``get_section``
    (which includes the trailing separator), the separator would otherwise be
    written twice — once from the agent's ``new_content`` and once from
    ``_collect_trailing_separator``.  Stripping the matching tail avoids the
    duplication while leaving any *different* content at the tail untouched.

    Matching is done right-to-left so only a suffix that exactly equals
    *natural_sep* (in order) is removed; a different comment at the tail is
    left alone.

    Returns the (possibly shorter) list; the input list is mutated.
    """
    sep_to_strip = list(natural_sep)
    while (
        sep_to_strip
        and raw_lines
        and raw_lines[-1].rstrip("\r") == sep_to_strip[-1].rstrip("\r")
    ):
        raw_lines.pop()
        sep_to_strip.pop()
    return raw_lines


class MarkdownDocument:
    """Surgical read/write access to a Markdown file's sections."""

    def __init__(self, filepath: str | Path) -> None:
        self._path = Path(filepath).resolve()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _read_raw(self) -> str:
        """Read the file without any newline translation (byte-faithful)."""
        with open(self._path, encoding="utf-8", newline="") as f:
            return f.read()

    def _read_text(self) -> str:
        return self._read_raw().replace("\r\n", "\n")

    def _read_lines(self) -> list[str]:
        return _split_lines(self._read_text())

    def _load(self) -> tuple[list[str], bool, bool]:
        """Return ``(lines, ends_with_newline, last_line_has_cr)``.

        Lines are split on ``"\\n"`` only and keep any trailing ``"\\r"``, so
        writing them back with ``"\\n".join`` reproduces every byte.
        """
        raw = self._read_raw()
        lines = _split_lines(raw)
        ends_nl = raw.endswith("\n") or raw == ""
        return lines, ends_nl, bool(lines and lines[-1].endswith("\r"))

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

    def _write_lines(
        self, lines: list[str], ends_nl: bool, last_cr: bool = False
    ) -> None:
        if lines and not ends_nl and not last_cr and lines[-1].endswith("\r"):
            lines[-1] = lines[-1][:-1]  # a new final line must not gain a CR
        content = "\n".join(lines) + ("\n" if ends_nl else "")
        self._path.write_bytes(content.encode("utf-8"))
        self._invalidate_cache()

    def _frontmatter(self) -> tuple[int, int] | None:
        return self._parsed().frontmatter

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_index(self) -> dict[str, Any]:
        """Return a nested tree of headings.

        Returns a dict with a single key ``"sections"`` whose value is a list
        of root-level section nodes.  Each node has:

        * ``heading`` (str): heading text
        * ``level`` (int): heading level (1–6); 0 for the frontmatter node
        * A leading ``{"heading": "frontmatter", "level": 0, ...}`` node is
          present when the file starts with a ``---`` YAML block.  It is
          addressed with ``path="frontmatter"`` and takes precedence over a
          top-level heading that is itself named "frontmatter".
        * ``path`` (str): dot-separated path from root to this node
        * ``children`` (list): child nodes (same structure)
        """
        parsed = self._parsed()
        sections = _build_index_tree(parsed.headings)
        if parsed.frontmatter is not None:
            sections.insert(
                0,
                {
                    "heading": FRONTMATTER_PATH,
                    "level": 0,
                    "path": FRONTMATTER_PATH,
                    "children": [],
                },
            )
        return {"sections": sections}

    def get_section(self, path: str, *, depth: int | None = None) -> str:
        """Return the heading line(s) + body text of the named section.

        ``path`` is a dot-separated heading path.  Literal dots in heading
        text are represented as ``\\.`` (e.g. ``"Root.v1\\.2\\.3"``).
        Raises ``KeyError`` if the path does not resolve.

        ``depth=None`` (default): return heading + body + all descendants.
        ``depth=0``: return heading + own body only, no child sections.
        ``depth=N`` (N ≥ 1): return heading + body + N levels of descendants.
        """
        parsed = self._parsed()
        lines = self._read_lines()
        if parsed.frontmatter is not None and _is_frontmatter_path(path):
            return "\n".join(lines[parsed.frontmatter[0] + 1 : parsed.frontmatter[1]])
        idx = _resolve_path(parsed.headings, path)
        return _section_text(parsed.headings, idx, lines, depth=depth)

    def search_sections(
        self,
        query: str,
        *,
        case_sensitive: bool = False,
        scope: str = "body",
    ) -> list[dict[str, Any]]:
        """Search sections for lines matching ``query`` (regex).

        ``scope``: ``"body"`` (default) searches section bodies, ``"headings"``
        searches heading text, ``"both"`` does both.

        Returns a list of match objects — one per section that contains at
        least one hit — sorted by order of first appearance in the file::

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

        ``line`` is 1-based line number within the file.  For a heading match
        ``line`` is the heading's line and ``text`` is the heading text.
        Only the section's *own body* is searched (not its children) so
        results are not duplicated across parent and child sections.
        Frontmatter lines are searched as the section ``"frontmatter"`` when
        the scope includes bodies.
        Raises ``re.error`` if ``query`` is not a valid regex and
        ``ValueError`` if ``scope`` is unknown.
        """
        if scope not in _SCOPES:
            raise ValueError(f"scope must be one of {sorted(_SCOPES)}; got {scope!r}")
        flags = 0 if case_sensitive else re.IGNORECASE
        pattern = re.compile(query, flags)  # raises re.error on invalid query
        in_body = scope in ("body", "both")
        in_headings = scope in ("headings", "both")

        parsed = self._parsed()
        headings = parsed.headings
        lines = self._read_lines()
        paths = _heading_paths(headings)

        results: list[dict[str, Any]] = []

        if in_body and parsed.frontmatter is not None:
            fm_matches = [
                {"line": i + 1, "text": lines[i]}
                for i in range(parsed.frontmatter[0] + 1, parsed.frontmatter[1])
                if pattern.search(lines[i])
            ]
            if fm_matches:
                results.append({"path": FRONTMATTER_PATH, "matches": fm_matches})

        for i, h in enumerate(headings):
            matches: list[dict[str, Any]] = []
            if in_headings and pattern.search(h.text):
                matches.append({"line": h.start_line + 1, "text": h.text})
            if in_body:
                # body: first line after heading markup up to the next heading
                body_end = (
                    headings[i + 1].start_line if i + 1 < len(headings) else len(lines)
                )
                for line_idx in range(h.end_line, body_end):
                    if pattern.search(lines[line_idx]):
                        matches.append({"line": line_idx + 1, "text": lines[line_idx]})
            if matches:
                results.append({"path": paths[i], "matches": matches})

        return results

    def replace_in_section(
        self,
        path: str,
        old: str,
        new: str,
        *,
        replace_all: bool = False,
    ) -> str:
        """Replace exact string ``old`` with ``new`` inside one section body.

        Only the section's own body is considered (heading line and child
        sections are excluded); for ``path="frontmatter"`` it is the text
        between the ``---`` delimiters.  The write is byte-exact outside the
        replaced spans.  Returns the unified diff.

        Raises ``ValueError`` if ``old`` is empty or equals ``new``, is not
        found, or matches more than once while ``replace_all`` is false, or if
        a frontmatter edit would produce invalid YAML.  ``KeyError`` if the
        path does not resolve.  The file is not modified on any error.
        """
        if old == "":
            raise ValueError("old must not be empty")
        if old == new:
            raise ValueError("old and new are identical; nothing to replace")

        raw = self._read_raw()
        parsed = _ParsedDocument.from_text(raw)
        # Line start offsets within the raw text (split on "\n" only).
        raw_lines = raw.split("\n")
        starts: list[int] = []
        off = 0
        for ln in raw_lines:
            starts.append(off)
            off += len(ln) + 1
        starts.append(len(raw) + 1)  # sentinel for the end-of-file line

        def offset(line: int) -> int:
            return min(starts[line], len(raw)) if line < len(starts) else len(raw)

        is_fm = parsed.frontmatter is not None and _is_frontmatter_path(path)
        if is_fm:
            assert parsed.frontmatter is not None
            first, last = parsed.frontmatter[0] + 1, parsed.frontmatter[1]
        else:
            idx = _resolve_path(parsed.headings, path)
            h = parsed.headings[idx]
            first = h.end_line
            last = (
                parsed.headings[idx + 1].start_line
                if idx + 1 < len(parsed.headings)
                else len(raw_lines)
            )
            # a trailing "" element from a final newline is not a body line
            if last == len(raw_lines) and raw.endswith("\n"):
                last -= 1
        seg_start = offset(first)
        seg_end = offset(last) if last > first else seg_start
        segment = raw[seg_start:seg_end]

        count = segment.count(old)
        if count == 0 and "\n" in old:
            # Clients send "\n"; retry with the file's CRLF endings.
            crlf_old = old.replace("\r\n", "\n").replace("\n", "\r\n")
            if segment.count(crlf_old):
                old = crlf_old
                new = new.replace("\r\n", "\n").replace("\n", "\r\n")
                count = segment.count(old)
        if count == 0:
            raise ValueError(f"old text not found in section {path!r}")
        if count > 1 and not replace_all:
            raise ValueError(
                f"old text matches {count} times in section {path!r}; "
                "add surrounding context to make it unique or pass replace_all=true"
            )
        new_segment = segment.replace(old, new)
        if is_fm:
            _check_frontmatter_edit(
                segment.replace("\r\n", "\n").split("\n"),
                new_segment.replace("\r\n", "\n").split("\n"),
            )
        new_raw = raw[:seg_start] + new_segment + raw[seg_end:]

        self._path.write_bytes(new_raw.encode("utf-8"))
        self._invalidate_cache()
        return "".join(
            difflib.unified_diff(
                raw.replace("\r\n", "\n").splitlines(keepends=True),
                new_raw.replace("\r\n", "\n").splitlines(keepends=True),
                fromfile=str(self._path),
                tofile=str(self._path) + " (patched)",
            )
        )

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

        At most one of ``before`` or ``after`` may be set.  ``under`` may be
        combined with ``before`` or ``after`` as a redundant parent
        confirmation: when both are supplied, ``under`` is validated against
        the parent implied by the sibling path, then stripped so placement
        proceeds with ``before``/``after`` alone.

        Valid combinations::

            # append at end
            add_section("## New", "body")
            # insert as last child of a section
            add_section("## New", "body", under="Root.Parent")
            # insert before a sibling (under is optional and validated)
            add_section("## New", "body", before="Root.Parent.Sibling")
            add_section("## New", "body", under="Root.Parent", before="Root.Parent.Sibling")
            # insert after a sibling
            add_section("## New", "body", after="Root.Parent.Sibling")
            add_section("## New", "body", under="Root.Parent", after="Root.Parent.Sibling")

        ``heading`` must start with one or more ``#`` characters followed by
        a space, e.g. ``"## New Section"``.

        The path arguments (``under``, ``before``, ``after``) use
        dot-separated heading paths.  Literal dots in heading text are
        represented as ``\\.`` (e.g. ``"Root.v1\\.2\\.3"``).
        """
        for anchor in (under, before, after):
            if anchor is not None and _is_frontmatter_path(anchor):
                if self._frontmatter() is not None:
                    raise ValueError(
                        "add_section cannot target the frontmatter block; "
                        "anchor on a heading path instead."
                    )
        if not re.match(r"^#{1,6} ", heading):
            raise ValueError(
                f"heading must start with 1–6 '#' characters followed by a space; "
                f"got {heading!r}"
            )

        if before is not None and after is not None:
            raise ValueError("before and after cannot both be specified.")

        # Determine whether we need to validate under against the sibling path.
        # Validation is deferred to after headings are parsed (we need indices).
        _check_under_consistency = under is not None and (
            before is not None or after is not None
        )

        # Re-read file right before writing to avoid races
        lines, ends_nl, last_cr = self._load()
        cr = _dominant_cr(lines)
        parsed = _ParsedDocument.from_text("\n".join(lines))
        headings = parsed.headings

        # Validate and strip under when combined with before/after.
        if _check_under_consistency:
            assert under is not None  # narrowing for type checker
            sibling = before if before is not None else after
            assert sibling is not None
            segs = _split_path(sibling)
            if len(segs) < 2:
                raise ValueError(
                    f"under={under!r} is redundant: {sibling!r} is a root-level "
                    "section with no parent heading. Remove under= and retry."
                )
            parent_path = ".".join(_escape_segment(s) for s in segs[:-1])
            under_idx = _resolve_path(headings, under)
            parent_idx = _resolve_path(headings, parent_path)
            if under_idx != parent_idx:
                raise ValueError(
                    f"under={under!r} does not match the parent of {sibling!r} "
                    f"— expected {parent_path!r}. Remove under= and retry."
                )
            # under is consistent — strip it; proceed with before/after alone
            under = None

        # Build the new block to insert (heading line + optional body)
        block_lines = [heading]
        if content:
            body = content.replace("\r\n", "\n").rstrip("\n")
            block_lines.append("")  # blank line after heading
            block_lines.extend(body.split("\n"))
        block_lines = _nl(block_lines, cr)
        # Trailing blank line separates the block from what follows; it is
        # dropped again below when the block ends the file.
        block_lines.append(cr)

        def insert_block(at: int, leading_blank: bool) -> None:
            block = ([cr] if leading_blank else []) + block_lines
            if at >= len(lines):
                block = block[:-1]  # nothing follows: no separator
            lines[at:at] = block

        if under is None and before is None and after is None:
            # Append at end of document, separated by one blank line
            insert_block(len(lines), bool(lines and lines[-1].strip() != ""))
        elif before is not None:
            idx = _resolve_path(headings, before)
            insert_at = headings[idx].start_line
            # Collapse any run of blank lines immediately before the target
            # heading down to at most one, to avoid double blank separators.
            end_of_blanks = insert_at
            while insert_at > 0 and lines[insert_at - 1].strip() == "":
                insert_at -= 1
            # NOTE: if the file starts with blank lines and the target heading is the
            # first heading, insert_at will reach 0 and those leading blanks will be
            # removed as a side effect. This is acceptable because leading blank lines
            # have no meaning in standard Markdown.
            del lines[insert_at:end_of_blanks]
            insert_block(insert_at, insert_at > 0)
        else:
            # after: insert after the whole target section (incl. children);
            # under: insert as last child of the target section.
            anchor = after if after is not None else under
            assert anchor is not None
            idx = _resolve_path(headings, anchor)
            _, section_end = _section_lines(headings, idx, lines, depth=None)
            insert_at = section_end
            while insert_at > 0 and lines[insert_at - 1].strip() == "":
                insert_at -= 1
            # Replace the trailing blank lines with exactly one separator
            del lines[insert_at:section_end]
            insert_block(insert_at, True)

        self._write_lines(lines, ends_nl, last_cr)

    def replace_section(self, path: str, new_content: str) -> None:
        """Replace the body of a section, preserving the heading line.

        ``path`` is a dot-separated heading path.  Literal dots in heading
        text are represented as ``\\.`` (e.g. ``"Root.v1\\.2\\.3"``).
        Writes to file and invalidates the cache.
        Raises ``KeyError`` if the path does not resolve.

        ``new_content`` is the **body only** — do not include the heading line.
        If ``new_content`` starts with a Markdown heading (``# …`` through
        ``###### …``), that line is silently stripped so the result is
        identical to passing body-only content.  This handles the common case
        where an agent includes the heading line in the replacement text.

        ``path="frontmatter"`` replaces the YAML between the ``---`` delimiters.
        Bytes outside the replaced span (line endings, trailing blank lines,
        a missing final newline) are preserved.
        """
        # Re-read right before write
        lines, ends_nl, last_cr = self._load()
        parsed = _ParsedDocument.from_text("\n".join(lines))
        new_lines = _replaced_lines(
            lines, parsed, path, new_content, _dominant_cr(lines)
        )
        self._write_lines(new_lines, ends_nl, last_cr)

    def patch_section(self, path: str, new_content: str) -> str:
        """Return a unified diff of what ``replace_section`` would do.

        ``path`` is a dot-separated heading path.  Literal dots in heading
        text are represented as ``\\.`` (e.g. ``"Root.v1\\.2\\.3"``).
        Does NOT write to file.

        ``new_content`` is the **body only** — do not include the heading line.
        If ``new_content`` starts with a Markdown heading (``# …`` through
        ``###### …``), that line is silently stripped so the resulting diff is
        identical to passing body-only content.  This handles the common case
        where an agent includes the heading line in the replacement text.
        """
        original_text = self._read_text()
        lines = _split_lines(original_text)
        parsed = _ParsedDocument.from_text(original_text)
        new_lines = _replaced_lines(lines, parsed, path, new_content, "")
        new_text = "\n".join(new_lines) + ("\n" if original_text.endswith("\n") else "")
        return "".join(
            difflib.unified_diff(
                original_text.splitlines(keepends=True),
                new_text.splitlines(keepends=True),
                fromfile=str(self._path),
                tofile=str(self._path) + " (patched)",
            )
        )

    def delete_section(self, path: str, *, include_children: bool = True) -> None:
        """Delete a section from the document and write to file.

        ``path`` is a dot-separated heading path.  Literal dots in heading
        text are represented as ``\\.`` (e.g. ``"Root.v1\\.2\\.3"``).
        With ``include_children=True`` (default): delete heading + body +
        all child sections.
        With ``include_children=False``: delete the heading + its own body
        only; child sections are promoted (their headings remain in place).
        Consecutive blank lines at the deletion point are collapsed to a
        single blank line; nothing else in the file is touched.
        Raises ``KeyError`` if the path does not resolve.
        """
        lines, ends_nl, last_cr = self._load()
        parsed = _ParsedDocument.from_text("\n".join(lines))
        if parsed.frontmatter is not None and _is_frontmatter_path(path):
            raise ValueError("delete_section cannot target the frontmatter block.")
        idx = _resolve_path(parsed.headings, path)

        start, end = _section_lines(
            parsed.headings, idx, lines, depth=None if include_children else 0
        )

        # When not including children, the end is at the first child heading.
        # That child heading starts right at `end`.  We want to delete only
        # the parent heading + its direct body.
        del lines[start:end]

        # Collapse the run of blank lines now meeting at the deletion site.
        lo = start
        while lo > 0 and lines[lo - 1].strip() == "":
            lo -= 1
        hi = start
        while hi < len(lines) and lines[hi].strip() == "":
            hi += 1
        if hi == len(lines):
            del lines[lo:hi]  # the deleted section ended the file
        elif hi - lo > 1:
            del lines[lo + 1 : hi]
        self._write_lines(lines, ends_nl, last_cr)


def _replaced_lines(
    lines: list[str],
    parsed: _ParsedDocument,
    path: str,
    new_content: str,
    cr: str,
) -> list[str]:
    """Return *lines* with the body of section *path* replaced (no I/O)."""
    if parsed.frontmatter is not None and _is_frontmatter_path(path):
        return _replace_frontmatter(lines, parsed.frontmatter, new_content, cr)
    new_content = _strip_leading_heading(new_content.replace("\r\n", "\n"))
    idx = _resolve_path(parsed.headings, path)
    h = parsed.headings[idx]

    # If new_content contains child headings, the agent is supplying a full
    # section replacement (heading + body + children).  Use depth=None so
    # the entire existing span (including children) is replaced atomically.
    # Otherwise use depth=0 to touch only the own body and leave children intact.
    depth: int | None = None if _new_content_has_child_headings(new_content) else 0
    start, own_body_end = _section_lines(parsed.headings, idx, lines, depth=depth)

    heading_end = h.end_line  # exclusive, 0-indexed; body begins here
    heading_lines = lines[start:heading_end]

    # Collect the separator: blank lines and HTML comment blocks that sit
    # between this section's content and the next heading.  These are
    # preserved verbatim so markers like <!-- BEGIN_TF_DOCS --> survive.
    natural_sep = _collect_trailing_separator(lines, own_body_end, heading_end)
    if natural_sep:
        trailing = natural_sep
    elif own_body_end >= len(lines):
        trailing = []  # end of file: nothing follows, no separator needed
    else:
        trailing = [cr]

    # Strip separator lines from the tail of new_content to prevent
    # duplication when the agent passes back content it read via get_section.
    stripped = new_content.rstrip("\n")
    raw_lines = stripped.split("\n") if stripped else []
    _strip_separator_from_tail(raw_lines, natural_sep)

    body_lines = [cr] + _nl(raw_lines, cr) if raw_lines else []
    return lines[:start] + heading_lines + body_lines + trailing + lines[own_body_end:]


SEARCH_MAX_FILE_BYTES = 1024 * 1024
SEARCH_MAX_TEXT_CHARS = 300
SEARCH_MAX_LIMIT = 1000


def search_files(
    directory: str | Path,
    glob: str,
    query: str,
    *,
    scope: str = "body",
    case_sensitive: bool = False,
    limit: int = 100,
    max_file_bytes: int = SEARCH_MAX_FILE_BYTES,
) -> dict[str, Any]:
    """Run ``search_sections`` over every file under *directory* matching *glob*.

    Returns ``{"matches": [{"file_path", "path", "line", "text"}, ...],
    "skipped": int, "truncated": bool, "limit": int}``.

    Files that cannot be read, are not valid UTF-8, are larger than
    *max_file_bytes* (default 1 MiB), or resolve outside *directory* (symlink
    escape) are skipped and counted in ``skipped``.  Each match ``text`` is
    cut to ``SEARCH_MAX_TEXT_CHARS`` characters.
    Matches are ordered by file path, then file order; at most *limit* are
    returned and ``truncated`` is true when more existed (``skipped`` is then
    only a lower bound).
    Raises ``ValueError`` (bad scope/limit/glob/directory; *limit* must be
    1..``SEARCH_MAX_LIMIT``; *glob* must be relative and contain no ``..``)
    or ``re.error``.
    """
    if not 1 <= limit <= SEARCH_MAX_LIMIT:
        raise ValueError(f"limit must be between 1 and {SEARCH_MAX_LIMIT}")
    if max_file_bytes < 1:
        raise ValueError("max_file_bytes must be >= 1")
    if Path(glob).is_absolute() or ".." in Path(glob).parts or glob.startswith("~"):
        raise ValueError(
            f"invalid glob {glob!r}: must be relative to directory and contain no '..'"
        )
    if scope not in _SCOPES:
        raise ValueError(f"scope must be one of {sorted(_SCOPES)}; got {scope!r}")
    re.compile(query)  # fail fast on an invalid regex
    root = Path(directory).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"not a directory: {directory}")
    try:
        candidates = sorted(p for p in root.glob(glob) if p.is_file())
    except (NotImplementedError, ValueError) as e:
        raise ValueError(f"invalid glob {glob!r}: {e}") from e

    matches: list[dict[str, Any]] = []
    skipped = 0
    truncated = False
    for file in candidates:
        if not file.resolve().is_relative_to(root):
            skipped += 1
            continue
        try:
            if file.stat().st_size > max_file_bytes:
                skipped += 1
                continue
            found = MarkdownDocument(file).search_sections(
                query, case_sensitive=case_sensitive, scope=scope
            )
        except (OSError, UnicodeError):
            skipped += 1
            continue
        for section in found:
            for m in section["matches"]:
                if len(matches) >= limit:
                    truncated = True
                    break
                matches.append(
                    {
                        "file_path": str(file),
                        "path": section["path"],
                        "line": m["line"],
                        "text": m["text"][:SEARCH_MAX_TEXT_CHARS],
                    }
                )
            if truncated:
                break
        if truncated:
            break
    return {
        "matches": matches,
        "skipped": skipped,
        "truncated": truncated,
        "limit": limit,
    }
