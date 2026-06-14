"""Comprehensive tests for MarkdownDocument."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from md_mcp.document import MarkdownDocument, _CACHE, _split_path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def write_md(tmp_path: Path, content: str, name: str = "test.md") -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# 1. get_index
# ---------------------------------------------------------------------------


class TestGetIndex:
    def test_no_headings_returns_empty_sections(self, tmp_path: Path) -> None:
        p = write_md(tmp_path, "Just some paragraph text.\n\nAnother paragraph.\n")
        doc = MarkdownDocument(p)
        result = doc.get_index()
        assert result == {"sections": []}

    def test_single_h1(self, tmp_path: Path) -> None:
        p = write_md(tmp_path, "# Hello World\n\nSome content.\n")
        doc = MarkdownDocument(p)
        result = doc.get_index()
        assert len(result["sections"]) == 1
        section = result["sections"][0]
        assert section["heading"] == "Hello World"
        assert section["level"] == 1
        assert section["path"] == "Hello World"
        assert section["children"] == []

    def test_multi_level_tree(self, tmp_path: Path) -> None:
        content = "# Root\n\n## Section A\n\n### Sub A1\n\n## Section B\n"
        p = write_md(tmp_path, content)
        doc = MarkdownDocument(p)
        result = doc.get_index()
        sections = result["sections"]
        assert len(sections) == 1
        root = sections[0]
        assert root["heading"] == "Root"
        assert len(root["children"]) == 2
        sec_a = root["children"][0]
        assert sec_a["heading"] == "Section A"
        assert sec_a["path"] == "Root.Section A"
        assert len(sec_a["children"]) == 1
        sub_a1 = sec_a["children"][0]
        assert sub_a1["heading"] == "Sub A1"
        assert sub_a1["path"] == "Root.Section A.Sub A1"
        sec_b = root["children"][1]
        assert sec_b["heading"] == "Section B"
        assert sec_b["path"] == "Root.Section B"

    def test_multiple_h1s(self, tmp_path: Path) -> None:
        content = "# First\n\n## Child\n\n# Second\n"
        p = write_md(tmp_path, content)
        doc = MarkdownDocument(p)
        result = doc.get_index()
        sections = result["sections"]
        assert len(sections) == 2
        assert sections[0]["heading"] == "First"
        assert sections[0]["path"] == "First"
        assert len(sections[0]["children"]) == 1
        assert sections[1]["heading"] == "Second"
        assert sections[1]["path"] == "Second"


# ---------------------------------------------------------------------------
# 2. get_section
# ---------------------------------------------------------------------------


class TestGetSection:
    def test_existing_path_returns_heading_and_body(self, tmp_path: Path) -> None:
        content = (
            "# Root\n\nIntro\n\n## Section A\n\nBody A\n\n## Section B\n\nBody B\n"
        )
        p = write_md(tmp_path, content)
        doc = MarkdownDocument(p)
        text = doc.get_section("Root.Section A")
        assert "## Section A" in text
        assert "Body A" in text

    def test_missing_path_raises_key_error(self, tmp_path: Path) -> None:
        p = write_md(tmp_path, "# Root\n\nContent\n")
        doc = MarkdownDocument(p)
        with pytest.raises(KeyError, match="NonExistent"):
            doc.get_section("Root.NonExistent")

    def test_include_children_true(self, tmp_path: Path) -> None:
        content = (
            "# Root\n\n"
            "## Section A\n\nBody A\n\n"
            "### Sub A1\n\nSub body\n\n"
            "## Section B\n\nBody B\n"
        )
        p = write_md(tmp_path, content)
        doc = MarkdownDocument(p)
        text = doc.get_section("Root.Section A", include_children=True)
        assert "## Section A" in text
        assert "Body A" in text
        assert "### Sub A1" in text
        assert "Sub body" in text
        # Must not include Section B
        assert "## Section B" not in text
        assert "Body B" not in text

    def test_include_children_false(self, tmp_path: Path) -> None:
        content = (
            "# Root\n\n"
            "## Section A\n\nBody A\n\n"
            "### Sub A1\n\nSub body\n\n"
            "## Section B\n\nBody B\n"
        )
        p = write_md(tmp_path, content)
        doc = MarkdownDocument(p)
        text = doc.get_section("Root.Section A", include_children=False)
        assert "## Section A" in text
        assert "Body A" in text
        # With include_children=False, stop at any next heading
        assert "### Sub A1" not in text

    def test_section_with_no_body(self, tmp_path: Path) -> None:
        content = "# Root\n\n## Empty\n\n## After\n\nContent\n"
        p = write_md(tmp_path, content)
        doc = MarkdownDocument(p)
        text = doc.get_section("Root.Empty")
        assert "## Empty" in text
        # Body is empty
        body = text.replace("## Empty", "").strip()
        assert body == ""

    def test_case_insensitive_path(self, tmp_path: Path) -> None:
        p = write_md(tmp_path, "# Hello World\n\nContent\n")
        doc = MarkdownDocument(p)
        # Should work with any capitalisation
        text = doc.get_section("hello world")
        assert "# Hello World" in text

    def test_missing_first_segment_raises_key_error(self, tmp_path: Path) -> None:
        p = write_md(tmp_path, "# Root\n\nContent\n")
        doc = MarkdownDocument(p)
        with pytest.raises(KeyError):
            doc.get_section("WrongRoot")


# ---------------------------------------------------------------------------
# 3. add_section
# ---------------------------------------------------------------------------


class TestAddSection:
    def test_append_no_anchor(self, tmp_path: Path) -> None:
        p = write_md(tmp_path, "# Root\n\nContent\n")
        doc = MarkdownDocument(p)
        doc.add_section("## New Section", "New body")
        text = p.read_text(encoding="utf-8")
        assert "## New Section" in text
        assert "New body" in text
        # New section should come after existing content
        assert text.index("## New Section") > text.index("# Root")

    def test_add_under(self, tmp_path: Path) -> None:
        content = "# Root\n\nContent\n\n## Child\n\nChild content\n"
        p = write_md(tmp_path, content)
        doc = MarkdownDocument(p)
        doc.add_section("### New Sub", "Sub body", under="Root")
        text = p.read_text(encoding="utf-8")
        assert "### New Sub" in text
        assert "Sub body" in text
        # Should appear after Child
        assert text.index("### New Sub") > text.index("## Child")

    def test_add_before(self, tmp_path: Path) -> None:
        content = "# Root\n\n## Section A\n\nBody A\n\n## Section B\n\nBody B\n"
        p = write_md(tmp_path, content)
        doc = MarkdownDocument(p)
        doc.add_section("## New", "New body", before="Root.Section B")
        text = p.read_text(encoding="utf-8")
        assert "## New" in text
        # New must come before Section B
        assert text.index("## New") < text.index("## Section B")
        # And after Section A
        assert text.index("## New") > text.index("## Section A")

    def test_add_after(self, tmp_path: Path) -> None:
        content = "# Root\n\n## Section A\n\nBody A\n\n## Section B\n\nBody B\n"
        p = write_md(tmp_path, content)
        doc = MarkdownDocument(p)
        doc.add_section("## New", "New body", after="Root.Section A")
        text = p.read_text(encoding="utf-8")
        assert "## New" in text
        # New must come after Section A and before Section B
        assert text.index("## New") > text.index("## Section A")
        assert text.index("## New") < text.index("## Section B")

    def test_invalid_heading_format_raises_value_error(self, tmp_path: Path) -> None:
        p = write_md(tmp_path, "# Root\n\nContent\n")
        doc = MarkdownDocument(p)
        with pytest.raises(ValueError, match="heading must start"):
            doc.add_section("New Section (no hash)", "body")

    def test_invalid_heading_no_space_raises_value_error(self, tmp_path: Path) -> None:
        p = write_md(tmp_path, "# Root\n\nContent\n")
        doc = MarkdownDocument(p)
        with pytest.raises(ValueError, match="heading must start"):
            doc.add_section("##NoSpace", "body")

    def test_invalid_anchor_path_raises_key_error(self, tmp_path: Path) -> None:
        p = write_md(tmp_path, "# Root\n\nContent\n")
        doc = MarkdownDocument(p)
        with pytest.raises(KeyError):
            doc.add_section("## New", "body", under="Root.NonExistent")

    def test_multiple_anchors_raises_value_error(self, tmp_path: Path) -> None:
        p = write_md(tmp_path, "# Root\n\n## A\n\n## B\n")
        doc = MarkdownDocument(p)
        with pytest.raises(ValueError):
            doc.add_section("## New", "body", before="Root.A", after="Root.B")

    def test_add_section_writes_to_file(self, tmp_path: Path) -> None:
        p = write_md(tmp_path, "# Root\n\nContent\n")
        doc = MarkdownDocument(p)
        doc.add_section("## New", "body")
        text = p.read_text(encoding="utf-8")
        assert "## New" in text

    def test_add_after_with_children(self, tmp_path: Path) -> None:
        """After a section with children: new section inserts after all children."""
        content = (
            "# Root\n\n"
            "## Section A\n\nBody A\n\n"
            "### Sub A1\n\nSub body\n\n"
            "## Section B\n\nBody B\n"
        )
        p = write_md(tmp_path, content)
        doc = MarkdownDocument(p)
        doc.add_section("## New", "New body", after="Root.Section A")
        text = p.read_text(encoding="utf-8")
        # Should be after Sub A1 but before Section B
        assert text.index("## New") > text.index("### Sub A1")
        assert text.index("## New") < text.index("## Section B")


# ---------------------------------------------------------------------------
# 4. replace_section
# ---------------------------------------------------------------------------


class TestReplaceSection:
    def test_replace_body_preserves_heading(self, tmp_path: Path) -> None:
        content = "# Root\n\nOld content\n\n## Other\n\nOther content\n"
        p = write_md(tmp_path, content)
        doc = MarkdownDocument(p)
        doc.replace_section("Root", "New content")
        text = p.read_text(encoding="utf-8")
        assert "# Root" in text
        assert "New content" in text
        assert "Old content" not in text

    def test_replace_heading_preserved(self, tmp_path: Path) -> None:
        content = "# Root\n\n## My Section\n\nOld body\n\n## Other\n"
        p = write_md(tmp_path, content)
        doc = MarkdownDocument(p)
        doc.replace_section("Root.My Section", "New body here")
        text = p.read_text(encoding="utf-8")
        # Heading unchanged
        assert "## My Section" in text
        assert "New body here" in text
        assert "Old body" not in text

    def test_replace_invalidates_cache(self, tmp_path: Path) -> None:
        content = "# Root\n\nOriginal content\n"
        p = write_md(tmp_path, content)
        doc = MarkdownDocument(p)
        # Populate cache
        _ = doc.get_index()
        assert str(p) in _CACHE

        doc.replace_section("Root", "Updated content")

        # Cache should be invalidated
        assert str(p) not in _CACHE

        # Re-read returns new content
        text2 = doc.get_section("Root")
        assert "Updated content" in text2
        assert "Original content" not in text2

    def test_replace_missing_path_raises_key_error(self, tmp_path: Path) -> None:
        p = write_md(tmp_path, "# Root\n\nContent\n")
        doc = MarkdownDocument(p)
        with pytest.raises(KeyError):
            doc.replace_section("Root.NonExistent", "New body")

    def test_replace_with_empty_content(self, tmp_path: Path) -> None:
        content = "# Root\n\nOld body\n\n## Other\n\nOther\n"
        p = write_md(tmp_path, content)
        doc = MarkdownDocument(p)
        doc.replace_section("Root", "")
        text = p.read_text(encoding="utf-8")
        assert "# Root" in text
        assert "Old body" not in text


# ---------------------------------------------------------------------------
# 5. patch_section
# ---------------------------------------------------------------------------


class TestPatchSection:
    def test_returns_unified_diff(self, tmp_path: Path) -> None:
        content = "# Root\n\nOld content\n"
        p = write_md(tmp_path, content)
        doc = MarkdownDocument(p)
        diff = doc.patch_section("Root", "New content")
        assert "---" in diff
        assert "+++" in diff
        assert "-Old content" in diff
        assert "+New content" in diff

    def test_does_not_modify_file(self, tmp_path: Path) -> None:
        content = "# Root\n\nOld content\n"
        p = write_md(tmp_path, content)
        doc = MarkdownDocument(p)
        _ = doc.patch_section("Root", "New content")
        # File should be unchanged
        assert p.read_text(encoding="utf-8") == content

    def test_no_diff_for_identical_content(self, tmp_path: Path) -> None:
        content = "# Root\n\nSame content\n"
        p = write_md(tmp_path, content)
        doc = MarkdownDocument(p)
        # Replace with same content
        diff = doc.patch_section("Root", "Same content")
        # Diff should be empty or show no changes
        # (the content is actually the same so no lines should differ)
        assert "-Same content" not in diff
        assert "+Same content" not in diff

    def test_missing_path_raises_key_error(self, tmp_path: Path) -> None:
        p = write_md(tmp_path, "# Root\n\nContent\n")
        doc = MarkdownDocument(p)
        with pytest.raises(KeyError):
            doc.patch_section("Root.NonExistent", "New body")


# ---------------------------------------------------------------------------
# 6. delete_section
# ---------------------------------------------------------------------------


class TestDeleteSection:
    def test_delete_leaf_section(self, tmp_path: Path) -> None:
        content = "# Root\n\n## Section A\n\nBody A\n\n## Section B\n\nBody B\n"
        p = write_md(tmp_path, content)
        doc = MarkdownDocument(p)
        doc.delete_section("Root.Section B")
        text = p.read_text(encoding="utf-8")
        assert "## Section B" not in text
        assert "Body B" not in text
        # Section A still present
        assert "## Section A" in text
        assert "Body A" in text

    def test_delete_with_include_children_true(self, tmp_path: Path) -> None:
        content = (
            "# Root\n\n"
            "## Section A\n\nBody A\n\n"
            "### Sub A1\n\nSub body\n\n"
            "## Section B\n\nBody B\n"
        )
        p = write_md(tmp_path, content)
        doc = MarkdownDocument(p)
        doc.delete_section("Root.Section A", include_children=True)
        text = p.read_text(encoding="utf-8")
        assert "## Section A" not in text
        assert "Body A" not in text
        assert "### Sub A1" not in text
        assert "Sub body" not in text
        # Section B still present
        assert "## Section B" in text
        assert "Body B" in text

    def test_delete_with_include_children_false_promotes_children(
        self, tmp_path: Path
    ) -> None:
        content = (
            "# Root\n\n"
            "## Section A\n\nBody A\n\n"
            "### Sub A1\n\nSub body\n\n"
            "## Section B\n\nBody B\n"
        )
        p = write_md(tmp_path, content)
        doc = MarkdownDocument(p)
        doc.delete_section("Root.Section A", include_children=False)
        text = p.read_text(encoding="utf-8")
        # Section A's heading and direct body removed
        assert "## Section A" not in text
        assert "Body A" not in text
        # Children are promoted (still in file)
        assert "### Sub A1" in text
        assert "Sub body" in text
        # Section B still present
        assert "## Section B" in text

    def test_delete_missing_path_raises_key_error(self, tmp_path: Path) -> None:
        p = write_md(tmp_path, "# Root\n\nContent\n")
        doc = MarkdownDocument(p)
        with pytest.raises(KeyError):
            doc.delete_section("Root.NonExistent")

    def test_delete_writes_to_file(self, tmp_path: Path) -> None:
        p = write_md(tmp_path, "# Root\n\n## ToDelete\n\nBody\n")
        doc = MarkdownDocument(p)
        doc.delete_section("Root.ToDelete")
        text = p.read_text(encoding="utf-8")
        assert "## ToDelete" not in text
        assert "Body" not in text


# ---------------------------------------------------------------------------
# 7. Cache behaviour
# ---------------------------------------------------------------------------


class TestCache:
    def test_cache_populated_after_read(self, tmp_path: Path) -> None:
        p = write_md(tmp_path, "# Root\n\nContent\n")
        doc = MarkdownDocument(p)
        _ = doc.get_index()
        assert str(p) in _CACHE

    def test_cache_invalidated_on_external_mtime_change(self, tmp_path: Path) -> None:
        content1 = "# Root\n\nOriginal\n"
        content2 = "# Root\n\n## New Section\n\nAdded\n"
        p = write_md(tmp_path, content1)
        doc = MarkdownDocument(p)

        # First read — cache populated
        index1 = doc.get_index()
        assert len(index1["sections"][0]["children"]) == 0

        # Modify file externally — change mtime
        time.sleep(0.01)  # ensure mtime differs
        p.write_text(content2, encoding="utf-8")
        # Force mtime change if filesystem has low resolution
        new_mtime = os.stat(p).st_mtime + 1
        os.utime(p, (new_mtime, new_mtime))

        # Second read — should parse fresh
        index2 = doc.get_index()
        assert len(index2["sections"][0]["children"]) == 1
        assert index2["sections"][0]["children"][0]["heading"] == "New Section"

    def test_cache_hit_avoids_reparse(self, tmp_path: Path) -> None:
        p = write_md(tmp_path, "# Root\n\nContent\n")
        doc = MarkdownDocument(p)
        _ = doc.get_index()
        cached_mtime, cached_parsed = _CACHE[str(p)]
        # Second read — same object returned
        _ = doc.get_index()
        _, second_parsed = _CACHE[str(p)]
        assert second_parsed is cached_parsed

    def test_write_invalidates_cache(self, tmp_path: Path) -> None:
        p = write_md(tmp_path, "# Root\n\nContent\n")
        doc = MarkdownDocument(p)
        _ = doc.get_index()
        assert str(p) in _CACHE

        doc.replace_section("Root", "New content")
        assert str(p) not in _CACHE


# ---------------------------------------------------------------------------
# 8. Edge cases / additional
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_ambiguous_siblings_first_match(self, tmp_path: Path) -> None:
        """Ambiguous paths resolve to the first match."""
        content = "# Root\n\n## Duplicate\n\nFirst\n\n## Duplicate\n\nSecond\n"
        p = write_md(tmp_path, content)
        doc = MarkdownDocument(p)
        text = doc.get_section("Root.Duplicate")
        assert "First" in text
        assert "Second" not in text

    def test_setext_heading_parsed(self, tmp_path: Path) -> None:
        """Setext headings (underlined) are recognised."""
        content = (
            "Root Heading\n============\n\nContent\n\nSection\n-------\n\nSub content\n"
        )
        p = write_md(tmp_path, content)
        doc = MarkdownDocument(p)
        index = doc.get_index()
        assert index["sections"][0]["heading"] == "Root Heading"
        assert index["sections"][0]["level"] == 1
        assert index["sections"][0]["children"][0]["heading"] == "Section"

    def test_get_section_h1_with_children(self, tmp_path: Path) -> None:
        """get_section on H1 with include_children=True returns full document."""
        content = "# Root\n\nIntro\n\n## A\n\nBody A\n"
        p = write_md(tmp_path, content)
        doc = MarkdownDocument(p)
        text = doc.get_section("Root", include_children=True)
        assert "# Root" in text
        assert "Intro" in text
        assert "## A" in text
        assert "Body A" in text

    def test_file_without_trailing_newline(self, tmp_path: Path) -> None:
        """Files without trailing newline are handled."""
        p = tmp_path / "test.md"
        p.write_bytes(b"# Root\n\nContent")
        doc = MarkdownDocument(p)
        index = doc.get_index()
        assert index["sections"][0]["heading"] == "Root"

    def test_add_section_empty_body(self, tmp_path: Path) -> None:
        """add_section with empty content doesn't crash."""
        p = write_md(tmp_path, "# Root\n\nContent\n")
        doc = MarkdownDocument(p)
        doc.add_section("## New", "")
        text = p.read_text(encoding="utf-8")
        assert "## New" in text

    def test_multiple_top_level_headings_path_resolution(self, tmp_path: Path) -> None:
        """Multiple H1s: path segments resolve under correct root."""
        content = "# First\n\n## Sub\n\nContent A\n\n# Second\n\n## Sub\n\nContent B\n"
        p = write_md(tmp_path, content)
        doc = MarkdownDocument(p)
        text_a = doc.get_section("First.Sub")
        text_b = doc.get_section("Second.Sub")
        assert "Content A" in text_a
        assert "Content B" in text_b
        assert "Content A" not in text_b
        assert "Content B" not in text_a


# ---------------------------------------------------------------------------
# 9. Dot-in-heading path escaping (BLOCKER 1)
# ---------------------------------------------------------------------------


class TestSplitPath:
    """Unit tests for the _split_path helper."""

    def test_plain_path_no_dots(self) -> None:
        assert _split_path("Root") == ["Root"]

    def test_plain_two_segment_path(self) -> None:
        assert _split_path("Root.Section A") == ["Root", "Section A"]

    def test_escaped_dot_not_split(self) -> None:
        """An escaped dot \\. stays as a literal dot in the segment."""
        assert _split_path("Root.v1\\.2\\.3") == ["Root", "v1.2.3"]

    def test_mixed_escaped_and_unescaped(self) -> None:
        assert _split_path("Root.Node\\.js.Sub") == ["Root", "Node.js", "Sub"]

    def test_only_escaped_dots(self) -> None:
        assert _split_path("v1\\.2\\.3") == ["v1.2.3"]


class TestDotInHeadingRoundTrip:
    """Heading text containing dots: index path and get_section round-trip."""

    def test_semver_heading_index_path(self, tmp_path: Path) -> None:
        """## v1.2.3 under # Root → path 'Root.v1\\.2\\.3'."""
        content = "# Root\n\nIntro\n\n## v1.2.3\n\nRelease notes\n"
        p = write_md(tmp_path, content)
        doc = MarkdownDocument(p)
        index = doc.get_index()
        children = index["sections"][0]["children"]
        assert len(children) == 1
        assert children[0]["heading"] == "v1.2.3"
        assert children[0]["path"] == "Root.v1\\.2\\.3"

    def test_semver_heading_get_section(self, tmp_path: Path) -> None:
        """get_section with escaped path retrieves the correct section."""
        content = "# Root\n\nIntro\n\n## v1.2.3\n\nRelease notes\n"
        p = write_md(tmp_path, content)
        doc = MarkdownDocument(p)
        text = doc.get_section("Root.v1\\.2\\.3")
        assert "## v1.2.3" in text
        assert "Release notes" in text

    def test_nodejs_heading_index_path(self, tmp_path: Path) -> None:
        """## Node.js under # Root → path 'Root.Node\\.js'."""
        content = "# Root\n\n## Node.js\n\nJS runtime\n"
        p = write_md(tmp_path, content)
        doc = MarkdownDocument(p)
        index = doc.get_index()
        child = index["sections"][0]["children"][0]
        assert child["heading"] == "Node.js"
        assert child["path"] == "Root.Node\\.js"

    def test_nodejs_heading_get_section(self, tmp_path: Path) -> None:
        """get_section with escaped path retrieves the Node.js section."""
        content = "# Root\n\n## Node.js\n\nJS runtime\n"
        p = write_md(tmp_path, content)
        doc = MarkdownDocument(p)
        text = doc.get_section("Root.Node\\.js")
        assert "## Node.js" in text
        assert "JS runtime" in text


# ---------------------------------------------------------------------------
# 10. delete_section blank-line cleanup (WARNING 2)
# ---------------------------------------------------------------------------


class TestDeleteSectionBlankLineCleanup:
    def test_no_double_blanks_after_delete(self, tmp_path: Path) -> None:
        """Deleting a section that is surrounded by blank lines must not
        leave consecutive blank lines in the output."""
        # Sections separated by blank lines; deleting "Middle" would naively
        # leave two consecutive blank lines between "Before body" and "After".
        content = (
            "# Root\n\n"
            "## Before\n\nBefore body\n\n"
            "## Middle\n\nMiddle body\n\n"
            "## After\n\nAfter body\n"
        )
        p = write_md(tmp_path, content)
        doc = MarkdownDocument(p)
        doc.delete_section("Root.Middle")
        text = p.read_text(encoding="utf-8")
        # No consecutive blank lines allowed
        assert "\n\n\n" not in text
        # Remaining sections still present
        assert "## Before" in text
        assert "Before body" in text
        assert "## After" in text
        assert "After body" in text
        # Deleted section gone
        assert "## Middle" not in text
        assert "Middle body" not in text
