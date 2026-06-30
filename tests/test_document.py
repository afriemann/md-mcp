"""Comprehensive tests for MarkdownDocument."""

from __future__ import annotations

import os
import re
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
        text = doc.get_section("Root.Section A", depth=None)
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
        text = doc.get_section("Root.Section A", depth=0)
        assert "## Section A" in text
        assert "Body A" in text
        # With depth=0, stop at any next heading
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

    def test_add_after_produces_exactly_one_blank_separator(
        self, tmp_path: Path
    ) -> None:
        """add_section with after= must leave exactly one blank line between
        the inserted section and the following sibling — no double blank lines."""
        content = "# Root\n\n## Section A\n\nBody A\n\n## Section B\n\nBody B\n"
        p = write_md(tmp_path, content)
        doc = MarkdownDocument(p)
        doc.add_section("## New", "New body", after="Root.Section A")
        text = p.read_text(encoding="utf-8")
        # Negative: no triple newline anywhere
        assert "\n\n\n" not in text
        # Positive: exactly the right separator sequence
        assert "Body A\n\n## New\n\nNew body\n\n## Section B" in text

    def test_add_before_no_double_blank(self, tmp_path: Path) -> None:
        """add_section with before= must not produce double blank lines,
        even when there are already multiple blank lines before the target heading."""
        # Use triple-blank-separated input to trigger the pre-existing-blank bug
        content = "# Root\n\n## Section A\n\nBody A\n\n\n## Section B\n\nBody B\n"
        p = write_md(tmp_path, content)
        doc = MarkdownDocument(p)
        doc.add_section("## New", "New body", before="Root.Section B")
        text = p.read_text(encoding="utf-8")
        assert "\n\n\n" not in text

    def test_add_under_no_double_blank(self, tmp_path: Path) -> None:
        """add_section with under= must not produce double blank lines."""
        content = (
            "# Root\n\n"
            "## Section A\n\nBody A\n\n"
            "### Sub A1\n\nSub body\n\n"
            "## Section B\n\nBody B\n"
        )
        p = write_md(tmp_path, content)
        doc = MarkdownDocument(p)
        doc.add_section("### Sub A2", "Sub body 2", under="Root.Section A")
        text = p.read_text(encoding="utf-8")
        assert "\n\n\n" not in text

    def test_add_before_first_heading_no_leading_blank(self, tmp_path: Path) -> None:
        """before= on the first heading must not prepend a blank line at start of file."""
        content = "# Root\n\n## Section A\n\nBody A\n"
        p = write_md(tmp_path, content)
        doc = MarkdownDocument(p)
        doc.add_section("## Intro", "intro body", before="Root")
        text = p.read_text(encoding="utf-8")
        assert text.startswith("## Intro\n"), (
            f"File must not start with blank line; got {text[:30]!r}"
        )
        assert "\n\n\n" not in text

    def test_add_after_last_section(self, tmp_path: Path) -> None:
        """after= on the last section in the file (section_end == len(lines))."""
        content = "# Root\n\n## Section A\n\nBody A\n"
        p = write_md(tmp_path, content)
        doc = MarkdownDocument(p)
        doc.add_section("## New", "New body", after="Root.Section A")
        text = p.read_text(encoding="utf-8")
        assert "Body A\n\n## New\n\nNew body\n" in text
        assert "\n\n\n" not in text


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

    def test_replace_own_body_preserves_child_sections(self, tmp_path: Path) -> None:
        content = "# Root\n\nOld preamble\n\n## Child\n\nChild body\n"
        p = write_md(tmp_path, content)
        doc = MarkdownDocument(p)
        doc.replace_section("Root", "New preamble")
        text = p.read_text(encoding="utf-8")
        assert "# Root" in text
        assert "New preamble" in text
        assert "Old preamble" not in text
        assert "## Child" in text
        assert "Child body" in text

    def test_replace_root_h1_does_not_wipe_document(self, tmp_path: Path) -> None:
        content = (
            "# Root\n\nRoot intro\n\n"
            "## Section A\n\nBody A\n\n"
            "## Section B\n\nBody B\n\n"
            "## Section C\n\nBody C\n"
        )
        p = write_md(tmp_path, content)
        doc = MarkdownDocument(p)
        doc.replace_section("Root", "New intro")
        text = p.read_text(encoding="utf-8")
        assert "## Section A" in text
        assert "Body A" in text
        assert "## Section B" in text
        assert "Body B" in text
        assert "## Section C" in text
        assert "Body C" in text
        assert "Root intro" not in text
        assert "New intro" in text

    def test_replace_mid_level_heading_preserves_children(self, tmp_path: Path) -> None:
        content = (
            "# Root\n\n"
            "## Parent\n\nParent preamble\n\n"
            "### Grandchild\n\nGrandchild body\n\n"
            "## Sibling\n\nSibling body\n"
        )
        p = write_md(tmp_path, content)
        doc = MarkdownDocument(p)
        doc.replace_section("Root.Parent", "New parent body")
        text = p.read_text(encoding="utf-8")
        assert "### Grandchild" in text
        assert "Grandchild body" in text
        assert "## Sibling" in text
        assert "Sibling body" in text
        assert "Parent preamble" not in text
        assert "New parent body" in text

    def test_replace_strips_leading_heading_from_new_content(
        self, tmp_path: Path
    ) -> None:
        """When new_content starts with the section heading, it must be stripped.

        Agents often include the heading line in new_content (e.g.
        ``"## My Section\\nNew body"``). replace_section already preserves the
        existing heading; the supplied heading line must be silently dropped so
        the result is identical to passing body-only content.
        """
        content = "# Root\n\n## My Section\n\nOld body\n\n## Other\n\nOther body\n"
        p = write_md(tmp_path, content)
        doc = MarkdownDocument(p)
        # Pass the heading as part of new_content (the common agent mistake)
        doc.replace_section("Root.My Section", "## My Section\nNew body here")
        text = p.read_text(encoding="utf-8")
        # Heading appears exactly once
        assert text.count("## My Section") == 1
        # Body was replaced correctly
        assert "New body here" in text
        assert "Old body" not in text
        # Other section untouched
        assert "## Other" in text
        assert "Other body" in text

    def test_replace_strips_leading_heading_any_level(self, tmp_path: Path) -> None:
        """Stripping works regardless of heading level (h1 through h6)."""
        content = "# Root\n\nOld body\n\n## Child\n\nChild body\n"
        p = write_md(tmp_path, content)
        doc = MarkdownDocument(p)
        doc.replace_section("Root", "# Root\nNew preamble")
        text = p.read_text(encoding="utf-8")
        assert text.count("# Root") == 1
        assert "New preamble" in text
        assert "Old body" not in text
        assert "## Child" in text

    def test_replace_with_child_sections_in_new_content_replaces_full_section(
        self, tmp_path: Path
    ) -> None:
        """When new_content contains child headings, the entire section
        (including existing children) is replaced atomically.

        This is the scenario where an agent reads the full section with
        get_section(depth=None), edits it, and passes the result back.
        The existing children must NOT be preserved separately — the
        replacement is the full new section tree.
        """
        content = (
            "# Root\n\n"
            "## Use cases\n\n"
            "Old preamble\n\n"
            "### Notes\n\n"
            "Old notes\n\n"
            "## Other\n\n"
            "Other body\n"
        )
        p = write_md(tmp_path, content)
        doc = MarkdownDocument(p)
        # Agent passes the full section including updated child
        new_content = "## Use cases\n\nNew preamble\n\n### Notes\n\nNew notes\n"
        doc.replace_section("Root.Use cases", new_content)
        text = p.read_text(encoding="utf-8")
        # Heading appears exactly once
        assert text.count("## Use cases") == 1
        # Notes child appears exactly once
        assert text.count("### Notes") == 1
        # Content updated
        assert "New preamble" in text
        assert "New notes" in text
        # Old content gone
        assert "Old preamble" not in text
        assert "Old notes" not in text
        # Sibling untouched
        assert "## Other" in text
        assert "Other body" in text

    def test_replace_with_child_sections_body_only_preserves_children(
        self, tmp_path: Path
    ) -> None:
        """When new_content contains no child headings, children are preserved
        (existing depth=0 behaviour is unchanged).
        """
        content = "# Root\n\nOld preamble\n\n## Child\n\nChild body\n"
        p = write_md(tmp_path, content)
        doc = MarkdownDocument(p)
        doc.replace_section("Root", "New preamble")
        text = p.read_text(encoding="utf-8")
        assert "New preamble" in text
        assert "Old preamble" not in text
        # Child preserved
        assert "## Child" in text
        assert "Child body" in text


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

    def test_patch_does_not_include_child_sections_in_diff(
        self, tmp_path: Path
    ) -> None:
        content = "# Root\n\nIntro\n\n## Child\n\nChild body\n"
        p = write_md(tmp_path, content)
        doc = MarkdownDocument(p)
        diff = doc.patch_section("Root", "New intro")
        assert "+New intro" in diff
        assert "-Intro" in diff
        assert "-## Child" not in diff
        assert "-Child body" not in diff

    def test_patch_strips_leading_heading_from_new_content(
        self, tmp_path: Path
    ) -> None:
        """When new_content starts with the section heading, the diff must not
        show the heading duplicated.

        This is the canonical agent mistake: including the heading line in
        new_content (e.g. ``"## Use cases\\nNew body"``).  The diff must be
        identical to passing body-only content and must NOT show the heading as
        an added line.
        """
        content = "# Root\n\n## Use cases\n\nOld body\n\n## Notes\n\nNotes body\n"
        p = write_md(tmp_path, content)
        doc = MarkdownDocument(p)
        # Simulate the agent mistake: heading included in new_content
        diff = doc.patch_section("Root.Use cases", "## Use cases\nNew body here")
        # The heading must not appear as an added line
        assert "+## Use cases" not in diff
        # Only the body change is shown
        assert "+New body here" in diff
        assert "-Old body" in diff
        # Notes section must not appear as a removed line
        assert "-## Notes" not in diff

    def test_patch_strips_leading_heading_produces_same_diff_as_body_only(
        self, tmp_path: Path
    ) -> None:
        """Passing heading+body must yield the exact same diff as body-only."""
        content = "# Root\n\nOld content\n"
        p = write_md(tmp_path, content)
        doc = MarkdownDocument(p)
        diff_with_heading = doc.patch_section("Root", "# Root\nNew content")
        diff_body_only = doc.patch_section("Root", "New content")
        assert diff_with_heading == diff_body_only

    def test_patch_with_child_sections_shows_no_duplication(
        self, tmp_path: Path
    ) -> None:
        """When new_content contains the full section (heading + children),
        the diff must not show duplicate child sections.

        This is the canonical agent failure: reading a section with depth=None,
        editing it, and passing the full text back — the diff must show only
        the body lines that actually changed, with no duplication of child
        headings.
        """
        content = (
            "# Root\n\n"
            "## Use cases\n\n"
            "Old preamble\n\n"
            "### Notes\n\n"
            "Old notes\n\n"
            "## Other\n\n"
            "Other body\n"
        )
        p = write_md(tmp_path, content)
        doc = MarkdownDocument(p)
        new_content = "## Use cases\n\nNew preamble\n\n### Notes\n\nNew notes\n"
        diff = doc.patch_section("Root.Use cases", new_content)
        # Only the changed lines should appear — body text replaced
        assert "-Old preamble" in diff
        assert "+New preamble" in diff
        assert "-Old notes" in diff
        assert "+New notes" in diff
        # ### Notes heading must NOT be duplicated (not added and not removed)
        assert "+### Notes" not in diff
        assert "-### Notes" not in diff
        # Sibling ## Other must not be added or removed (only appears as context at most)
        assert "+## Other" not in diff
        assert "-## Other" not in diff


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
        """get_section on H1 with depth=None returns full document."""
        content = "# Root\n\nIntro\n\n## A\n\nBody A\n"
        p = write_md(tmp_path, content)
        doc = MarkdownDocument(p)
        text = doc.get_section("Root", depth=None)
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


# ---------------------------------------------------------------------------
# 11. get_section depth parameter
# ---------------------------------------------------------------------------

# Shared fixture content for depth tests
_DEPTH_MD = (
    "# Root\n\n"
    "Root body.\n\n"
    "## Child A\n\n"
    "Child A body.\n\n"
    "### Grandchild A1\n\n"
    "Grandchild A1 body.\n\n"
    "### Grandchild A2\n\n"
    "Grandchild A2 body.\n\n"
    "## Child B\n\n"
    "Child B body.\n"
)


class TestGetSectionDepth:
    def test_depth_none_returns_full_subtree(self, tmp_path: Path) -> None:
        """depth=None (default) returns heading + body + all descendants."""
        p = write_md(tmp_path, _DEPTH_MD)
        doc = MarkdownDocument(p)
        text = doc.get_section("Root.Child A")  # default depth=None
        assert "## Child A" in text
        assert "Child A body." in text
        assert "### Grandchild A1" in text
        assert "Grandchild A1 body." in text
        assert "### Grandchild A2" in text
        assert "Grandchild A2 body." in text
        # Must not include Child B
        assert "## Child B" not in text
        assert "Child B body." not in text

    def test_depth_zero_returns_heading_and_own_body_only(self, tmp_path: Path) -> None:
        """depth=0 returns heading + own body, no child sections."""
        p = write_md(tmp_path, _DEPTH_MD)
        doc = MarkdownDocument(p)
        text = doc.get_section("Root.Child A", depth=0)
        assert "## Child A" in text
        assert "Child A body." in text
        assert "### Grandchild A1" not in text
        assert "Grandchild A1 body." not in text
        assert "### Grandchild A2" not in text

    def test_depth_one_includes_immediate_children_only(self, tmp_path: Path) -> None:
        """depth=1 returns heading + body + immediate children, not grandchildren."""
        p = write_md(tmp_path, _DEPTH_MD)
        doc = MarkdownDocument(p)
        # Request Child A with depth=1 — should include Grandchild A1 & A2
        # (they are immediate children of Child A)
        text = doc.get_section("Root.Child A", depth=1)
        assert "## Child A" in text
        assert "Child A body." in text
        assert "### Grandchild A1" in text
        assert "Grandchild A1 body." in text
        assert "### Grandchild A2" in text
        assert "Grandchild A2 body." in text
        # Child B is a sibling (same level), not a child — must NOT appear
        assert "## Child B" not in text

    def test_depth_one_from_root_includes_children_not_grandchildren(
        self, tmp_path: Path
    ) -> None:
        """depth=1 from Root returns Child A + Child B but NOT grandchildren."""
        p = write_md(tmp_path, _DEPTH_MD)
        doc = MarkdownDocument(p)
        text = doc.get_section("Root", depth=1)
        assert "# Root" in text
        assert "Root body." in text
        assert "## Child A" in text
        assert "Child A body." in text
        assert "## Child B" in text
        assert "Child B body." in text
        # Grandchildren must NOT appear
        assert "### Grandchild A1" not in text
        assert "Grandchild A1 body." not in text
        assert "### Grandchild A2" not in text

    def test_depth_two_includes_children_and_grandchildren(
        self, tmp_path: Path
    ) -> None:
        """depth=2 from Root returns children + grandchildren."""
        p = write_md(tmp_path, _DEPTH_MD)
        doc = MarkdownDocument(p)
        text = doc.get_section("Root", depth=2)
        assert "# Root" in text
        assert "## Child A" in text
        assert "### Grandchild A1" in text
        assert "Grandchild A1 body." in text
        assert "### Grandchild A2" in text
        assert "## Child B" in text

    def test_depth_zero_on_leaf_same_as_depth_none(self, tmp_path: Path) -> None:
        """depth=0 on a leaf section (no children) returns same as depth=None."""
        p = write_md(tmp_path, _DEPTH_MD)
        doc = MarkdownDocument(p)
        text_zero = doc.get_section("Root.Child A.Grandchild A1", depth=0)
        text_none = doc.get_section("Root.Child A.Grandchild A1", depth=None)
        assert text_zero == text_none
        assert "### Grandchild A1" in text_zero
        assert "Grandchild A1 body." in text_zero


# ---------------------------------------------------------------------------
# 12. search_sections
# ---------------------------------------------------------------------------

# Shared fixture content for search_sections tests
_SEARCH_MD = (
    "# Root\n\n"
    "Root intro line.\n\n"
    "## Alpha\n\n"
    "Alpha body line one.\n"
    "Alpha body line two.\n\n"
    "### Alpha Sub\n\n"
    "Alpha sub body: the word needle is here.\n\n"
    "## Beta\n\n"
    "Beta body with NEEDLE in uppercase.\n\n"
    "## Gamma\n\n"
    "Gamma has no matches.\n"
)


class TestSearchSections:
    def test_no_matches_returns_empty_list(self, tmp_path: Path) -> None:
        p = write_md(tmp_path, _SEARCH_MD)
        doc = MarkdownDocument(p)
        result = doc.search_sections("zzznotfound")
        assert result == []

    def test_single_match_single_section(self, tmp_path: Path) -> None:
        """A term appearing only in one section returns one result."""
        p = write_md(tmp_path, _SEARCH_MD)
        doc = MarkdownDocument(p)
        result = doc.search_sections("Root intro line")
        assert len(result) == 1
        assert result[0]["path"] == "Root"
        assert len(result[0]["matches"]) == 1
        match = result[0]["matches"][0]
        assert "Root intro line" in match["text"]
        assert match["line"] >= 1  # 1-based

    def test_multiple_matches_same_section(self, tmp_path: Path) -> None:
        """Multiple matching lines in one section → one result with multiple entries."""
        p = write_md(tmp_path, _SEARCH_MD)
        doc = MarkdownDocument(p)
        result = doc.search_sections("Alpha body line")
        assert len(result) == 1
        assert result[0]["path"] == "Root.Alpha"
        assert len(result[0]["matches"]) == 2

    def test_matches_in_multiple_sections_in_file_order(self, tmp_path: Path) -> None:
        """Matches in multiple sections → multiple results in file order."""
        p = write_md(tmp_path, _SEARCH_MD)
        doc = MarkdownDocument(p)
        # "needle" appears in Alpha Sub (lowercase) and Beta (uppercase as NEEDLE)
        result = doc.search_sections("needle", case_sensitive=False)
        assert len(result) == 2
        # File order: Alpha Sub comes before Beta
        assert result[0]["path"] == "Root.Alpha.Alpha Sub"
        assert result[1]["path"] == "Root.Beta"

    def test_case_insensitive_by_default(self, tmp_path: Path) -> None:
        """Default (case_sensitive=False): uppercase query matches lowercase body."""
        p = write_md(tmp_path, _SEARCH_MD)
        doc = MarkdownDocument(p)
        result = doc.search_sections("ALPHA BODY LINE ONE")
        assert len(result) == 1
        assert result[0]["path"] == "Root.Alpha"

    def test_case_sensitive_no_match(self, tmp_path: Path) -> None:
        """case_sensitive=True: query must match exact case."""
        p = write_md(tmp_path, _SEARCH_MD)
        doc = MarkdownDocument(p)
        # "NEEDLE" in uppercase only appears in Beta, not Alpha Sub (lowercase "needle")
        result = doc.search_sections("NEEDLE", case_sensitive=True)
        assert len(result) == 1
        assert result[0]["path"] == "Root.Beta"

    def test_regex_pattern_matches(self, tmp_path: Path) -> None:
        """Regex pattern (e.g. \\d+) matches correctly."""
        content = "# Root\n\nNo numbers here.\n\n## Numbers\n\nValue: 42 and 7.\n"
        p = write_md(tmp_path, content)
        doc = MarkdownDocument(p)
        result = doc.search_sections(r"\d+")
        assert len(result) == 1
        assert result[0]["path"] == "Root.Numbers"
        # Both numbers on the same line → one match entry
        assert len(result[0]["matches"]) == 1

    def test_invalid_regex_raises_re_error(self, tmp_path: Path) -> None:
        """Invalid regex raises re.error."""
        p = write_md(tmp_path, _SEARCH_MD)
        doc = MarkdownDocument(p)
        with pytest.raises(re.error):
            doc.search_sections("[invalid")

    def test_own_body_only_not_children(self, tmp_path: Path) -> None:
        """A term in a child section does NOT appear in the parent's result."""
        p = write_md(tmp_path, _SEARCH_MD)
        doc = MarkdownDocument(p)
        # "needle" is only in the Alpha Sub body, not in Alpha's own body
        result = doc.search_sections("needle", case_sensitive=True)
        # Exactly one result (Alpha Sub), NOT Root.Alpha
        paths = [r["path"] for r in result]
        assert "Root.Alpha.Alpha Sub" in paths
        assert "Root.Alpha" not in paths

    def test_line_numbers_are_one_based(self, tmp_path: Path) -> None:
        """Returned line numbers are 1-based file line numbers."""
        p = write_md(tmp_path, _SEARCH_MD)
        doc = MarkdownDocument(p)
        result = doc.search_sections("Root intro line")
        assert len(result) == 1
        line_num = result[0]["matches"][0]["line"]
        # "Root intro line." is on line 3 (1-based) in _SEARCH_MD
        assert line_num == 3
