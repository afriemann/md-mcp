"""Tests for frontmatter addressing, replace_in_section, heading search,
search_files and template-file byte-exactness."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import md_mcp.server as server
from md_mcp.document import MarkdownDocument

AGENT = (
    "---\n"
    "description: Reviews code\n"
    "mode: subagent\n"
    "---\n"
    "# Agent\n"
    "\n"
    "Intro line.\n"
    "\n"
    "## Rules\n"
    "\n"
    "Be nice.\n"
)

TMPL = (
    "---\n"
    "description: {{ .desc }}\n"
    "---\n"
    "# Agent\n"
    "\n"
    "Intro.\n"
    "{{- if .enabled }}\n"
    "Enabled line.\n"
    "{{- end }}\n"
    '{{ template "x"\n'
    "# not a heading\n"
    "}}\n"
    "Tail line.\n"
    "\n"
    "```\n"
    "# in fence\n"
    "```\n"
    "\n"
    "## Next\n"
    "\n"
    "Body.\n"
)


def write(tmp_path: Path, text: str, name: str = "a.md") -> Path:
    p = tmp_path / name
    p.write_bytes(text.encode("utf-8"))
    return p


class TestFrontmatterIndex:
    def test_index_has_frontmatter_node_and_real_sections(self, tmp_path: Path) -> None:
        idx = MarkdownDocument(write(tmp_path, AGENT)).get_index()["sections"]
        assert idx[0] == {
            "heading": "frontmatter",
            "level": 0,
            "path": "frontmatter",
            "children": [],
        }
        assert idx[1]["heading"] == "Agent"
        assert [c["heading"] for c in idx[1]["children"]] == ["Rules"]
        assert len(idx) == 2

    def test_no_frontmatter_no_node(self, tmp_path: Path) -> None:
        idx = MarkdownDocument(write(tmp_path, "# A\n\nx\n")).get_index()["sections"]
        assert [n["heading"] for n in idx] == ["A"]

    def test_unclosed_frontmatter_is_not_frontmatter(self, tmp_path: Path) -> None:
        idx = MarkdownDocument(write(tmp_path, "---\n# A\n")).get_index()["sections"]
        assert all(n["heading"] != "frontmatter" for n in idx)

    def test_get_section_frontmatter_raw(self, tmp_path: Path) -> None:
        doc = MarkdownDocument(write(tmp_path, AGENT))
        assert (
            doc.get_section("frontmatter")
            == "description: Reviews code\nmode: subagent"
        )

    def test_heading_named_frontmatter_without_block_is_normal(
        self, tmp_path: Path
    ) -> None:
        doc = MarkdownDocument(write(tmp_path, "# frontmatter\n\nbody\n"))
        assert "body" in doc.get_section("frontmatter")

    def test_add_and_delete_reject_frontmatter(self, tmp_path: Path) -> None:
        p = write(tmp_path, AGENT)
        doc = MarkdownDocument(p)
        with pytest.raises(ValueError):
            doc.delete_section("frontmatter")
        with pytest.raises(ValueError):
            doc.add_section("## X", "y", after="frontmatter")
        with pytest.raises(ValueError):
            doc.add_section("## X", "y", under="frontmatter")
        assert p.read_text() == AGENT


class TestFrontmatterEdit:
    def test_replace_in_section_frontmatter_changes_only_that_line(
        self, tmp_path: Path
    ) -> None:
        p = write(tmp_path, AGENT)
        MarkdownDocument(p).replace_in_section(
            "frontmatter", "Reviews code", "Reviews code carefully"
        )
        assert p.read_text() == AGENT.replace("Reviews code", "Reviews code carefully")

    def test_invalid_yaml_rejected_file_unchanged(self, tmp_path: Path) -> None:
        p = write(tmp_path, AGENT)
        doc = MarkdownDocument(p)
        with pytest.raises(ValueError, match="YAML"):
            doc.replace_in_section("frontmatter", "mode: subagent", "mode: [unclosed")
        with pytest.raises(ValueError, match="YAML"):
            doc.replace_section("frontmatter", "a: b: c: [")
        assert p.read_bytes() == AGENT.encode()

    def test_replace_section_frontmatter_keeps_delimiters(self, tmp_path: Path) -> None:
        p = write(tmp_path, AGENT)
        MarkdownDocument(p).replace_section("frontmatter", "description: New\n")
        assert p.read_text() == AGENT.replace(
            "description: Reviews code\nmode: subagent\n", "description: New\n"
        )

    def test_patch_section_frontmatter_is_dry_run(self, tmp_path: Path) -> None:
        p = write(tmp_path, AGENT)
        diff = MarkdownDocument(p).patch_section("frontmatter", "description: New")
        assert "+description: New" in diff
        assert p.read_text() == AGENT

    def test_template_frontmatter_not_yaml_checked(self, tmp_path: Path) -> None:
        p = write(tmp_path, TMPL)
        MarkdownDocument(p).replace_in_section("frontmatter", ".desc", ".other")
        assert "{{ .other }}" in p.read_text()


class TestReplaceInSection:
    def test_absent_old_errors_and_leaves_bytes(self, tmp_path: Path) -> None:
        p = write(tmp_path, AGENT)
        with pytest.raises(ValueError, match="not found"):
            MarkdownDocument(p).replace_in_section("Agent", "nope", "x")
        assert p.read_bytes() == AGENT.encode()

    def test_ambiguous_old_errors_with_count(self, tmp_path: Path) -> None:
        text = "# A\n\nfoo foo\nfoo\n"
        p = write(tmp_path, text)
        with pytest.raises(ValueError, match="3 times"):
            MarkdownDocument(p).replace_in_section("A", "foo", "bar")
        assert p.read_bytes() == text.encode()

    def test_replace_all(self, tmp_path: Path) -> None:
        p = write(tmp_path, "# A\n\nfoo foo\nfoo\n")
        MarkdownDocument(p).replace_in_section("A", "foo", "bar", replace_all=True)
        assert p.read_text() == "# A\n\nbar bar\nbar\n"

    def test_old_equals_new_and_empty_old_error(self, tmp_path: Path) -> None:
        p = write(tmp_path, AGENT)
        doc = MarkdownDocument(p)
        with pytest.raises(ValueError):
            doc.replace_in_section("Agent", "Intro", "Intro")
        with pytest.raises(ValueError):
            doc.replace_in_section("Agent", "", "x")

    def test_scoped_to_section_body_only(self, tmp_path: Path) -> None:
        text = "# A\n\nword\n\n## B\n\nword\n"
        p = write(tmp_path, text)
        # "word" occurs once in A's own body; the child's occurrence is excluded
        MarkdownDocument(p).replace_in_section("A", "word", "other")
        assert p.read_text() == "# A\n\nother\n\n## B\n\nword\n"

    def test_heading_line_excluded(self, tmp_path: Path) -> None:
        p = write(tmp_path, "# Title\n\nbody\n")
        with pytest.raises(ValueError, match="not found"):
            MarkdownDocument(p).replace_in_section("Title", "Title", "X")

    def test_no_trailing_newline_and_crlf_preserved(self, tmp_path: Path) -> None:
        raw = b"# A\r\n\r\nfoo\r\nbar"
        p = tmp_path / "c.md"
        p.write_bytes(raw)
        MarkdownDocument(p).replace_in_section("A", "bar", "baz")
        assert p.read_bytes() == b"# A\r\n\r\nfoo\r\nbaz"

    def test_last_section_with_no_trailing_newline(self, tmp_path: Path) -> None:
        p = tmp_path / "n.md"
        p.write_bytes(b"# A\n\nfoo")
        MarkdownDocument(p).replace_in_section("A", "foo", "bar\n")
        assert p.read_bytes() == b"# A\n\nbar\n"

    def test_returns_diff(self, tmp_path: Path) -> None:
        p = write(tmp_path, AGENT)
        diff = MarkdownDocument(p).replace_in_section("Agent.Rules", "nice", "kind")
        assert "-Be nice." in diff and "+Be kind." in diff


class TestTemplateRoundTrip:
    def test_index_ignores_template_and_fence_hashes(self, tmp_path: Path) -> None:
        idx = MarkdownDocument(write(tmp_path, TMPL, "t.md.tmpl")).get_index()
        top = idx["sections"]
        assert [n["heading"] for n in top] == ["frontmatter", "Agent"]
        assert [c["heading"] for c in top[1]["children"]] == ["Next"]

    def test_replace_in_section_only_intended_line_differs(
        self, tmp_path: Path
    ) -> None:
        p = write(tmp_path, TMPL, "t.md.tmpl")
        MarkdownDocument(p).replace_in_section("Agent", "Tail line.", "Tail changed.")
        assert p.read_bytes() == (TMPL.replace("Tail line.", "Tail changed.")).encode()

    def test_replace_section_preserves_untouched_bytes(self, tmp_path: Path) -> None:
        p = write(tmp_path, TMPL, "t.md.tmpl")
        MarkdownDocument(p).replace_section("Agent.Next", "New body.")
        assert p.read_bytes() == (TMPL.replace("Body.\n", "New body.\n")).encode()

    def test_replace_section_template_lines_in_section(self, tmp_path: Path) -> None:
        p = write(tmp_path, TMPL, "t.md.tmpl")
        doc = MarkdownDocument(p)
        body = doc.get_section("Agent", depth=0).split("\n", 2)[2]
        doc.replace_section("Agent", body.replace("Intro.", "Intro 2."))
        assert p.read_bytes() == (TMPL.replace("Intro.", "Intro 2.")).encode()

    def test_add_section_preserves_untouched_bytes(self, tmp_path: Path) -> None:
        p = write(tmp_path, TMPL, "t.md.tmpl")
        MarkdownDocument(p).add_section("## Last", "end", after="Agent.Next")
        assert p.read_bytes() == (TMPL + "\n## Last\n\nend\n").encode()

    def test_no_trailing_newline_preserved_by_replace_section(
        self, tmp_path: Path
    ) -> None:
        p = tmp_path / "n.md"
        p.write_bytes(b"# A\n\nx\n\n## B\n\ny")
        MarkdownDocument(p).replace_section("A", "z")
        assert p.read_bytes() == b"# A\n\nz\n\n## B\n\ny"


class TestSearchScope:
    def test_headings_scope_finds_by_heading(self, tmp_path: Path) -> None:
        doc = MarkdownDocument(write(tmp_path, AGENT))
        res = doc.search_sections("^rules$", scope="headings")
        assert res == [
            {"path": "Agent.Rules", "matches": [{"line": 9, "text": "Rules"}]}
        ]

    def test_headings_scope_does_not_search_bodies(self, tmp_path: Path) -> None:
        assert (
            MarkdownDocument(write(tmp_path, AGENT)).search_sections(
                "nice", scope="headings"
            )
            == []
        )

    def test_default_equals_body_and_matches_legacy_shape(self, tmp_path: Path) -> None:
        doc = MarkdownDocument(write(tmp_path, "# R\n\nfoo\n\n## C\n\nfoo bar\n"))
        expected = [
            {"path": "R", "matches": [{"line": 3, "text": "foo"}]},
            {"path": "R.C", "matches": [{"line": 7, "text": "foo bar"}]},
        ]
        assert doc.search_sections("foo") == expected
        assert doc.search_sections("foo", scope="body") == expected
        # heading text "R" is not searched by default
        assert doc.search_sections("^R$") == []

    def test_both_scope(self, tmp_path: Path) -> None:
        doc = MarkdownDocument(write(tmp_path, "# Foo\n\nfoo here\n"))
        res = doc.search_sections("foo", scope="both")
        assert res == [
            {
                "path": "Foo",
                "matches": [
                    {"line": 1, "text": "Foo"},
                    {"line": 3, "text": "foo here"},
                ],
            }
        ]

    def test_frontmatter_searchable_in_body_scope(self, tmp_path: Path) -> None:
        res = MarkdownDocument(write(tmp_path, AGENT)).search_sections("subagent")
        assert res[0]["path"] == "frontmatter"

    def test_invalid_scope(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            MarkdownDocument(write(tmp_path, AGENT)).search_sections("x", scope="all")


class TestSearchFiles:
    def _populate(self, tmp_path: Path) -> None:
        write(tmp_path, AGENT, "one.md")
        write(tmp_path, AGENT.replace("Reviews code", "Other"), "two.md")
        (tmp_path / "bad.md").write_bytes(b"\xff\xfe\x00bad")
        sub = tmp_path / "sub"
        sub.mkdir()
        write(sub, "# Sub\n\nBe nice here too.\n", "three.md")

    def test_finds_phrase_across_files(self, tmp_path: Path) -> None:
        self._populate(tmp_path)
        res = server.search_files(str(tmp_path), "*.md", "be nice")
        assert {Path(m["file_path"]).name for m in res["matches"]} == {
            "one.md",
            "two.md",
        }
        assert res["skipped"] == 1
        assert res["truncated"] is False
        m = res["matches"][0]
        assert set(m) == {"file_path", "path", "line", "text"}

    def test_recursive_glob(self, tmp_path: Path) -> None:
        self._populate(tmp_path)
        res = server.search_files(str(tmp_path), "**/*.md", "be nice")
        assert len(res["matches"]) == 3

    def test_truncation_flagged(self, tmp_path: Path) -> None:
        self._populate(tmp_path)
        res = server.search_files(str(tmp_path), "*.md", "be nice", limit=1)
        assert len(res["matches"]) == 1 and res["truncated"] is True

    def test_headings_scope(self, tmp_path: Path) -> None:
        self._populate(tmp_path)
        res = server.search_files(str(tmp_path), "*.md", "^rules$", scope="headings")
        assert len(res["matches"]) == 2

    def test_errors(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            server.search_files(str(tmp_path / "nope"), "*.md", "x")
        with pytest.raises(re.error):
            server.search_files(str(tmp_path), "*.md", "(")
        with pytest.raises(ValueError):
            server.search_files(str(tmp_path), "*.md", "x", limit=0)

    def test_respects_allowed_roots(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._populate(tmp_path)
        monkeypatch.setattr(server, "_allowed_roots", [tmp_path / "sub"])
        with pytest.raises(PermissionError):
            server.search_files(str(tmp_path), "*.md", "x")


class TestServerTools:
    def test_replace_in_section_tool(self, tmp_path: Path) -> None:
        p = write(tmp_path, AGENT)
        out = server.replace_in_section(str(p), "frontmatter", "Reviews", "Audits")
        assert "+description: Audits code" in out
        with pytest.raises(ValueError):
            server.replace_in_section(str(p), "frontmatter", "zzz", "y")

    def test_search_sections_tool_scope(self, tmp_path: Path) -> None:
        p = write(tmp_path, AGENT)
        assert (
            server.search_sections(str(p), "rules", scope="headings")[0]["path"]
            == "Agent.Rules"
        )
        with pytest.raises(ValueError):
            server.search_sections(str(p), "x", scope="bogus")


def _bytes(p: Path) -> bytes:
    return p.read_bytes()


class TestFrontmatterDetection:
    HR_DOC = "---\n\n# Title\n\nintro\n\n## Sub\n\ntext\n\n---\n\n# After\n"

    def test_horizontal_rule_document_keeps_headings(self, tmp_path: Path) -> None:
        idx = MarkdownDocument(write(tmp_path, self.HR_DOC)).get_index()["sections"]
        assert [n["heading"] for n in idx] == ["Title", "After"]
        assert idx[0]["children"][0]["heading"] == "Sub"

    def test_list_between_rules_is_not_frontmatter(self, tmp_path: Path) -> None:
        idx = MarkdownDocument(write(tmp_path, "---\n- a\n- b\n---\n# H\n")).get_index()
        assert [n["heading"] for n in idx["sections"]] == ["H"]

    def test_template_conditional_frontmatter_detected(self, tmp_path: Path) -> None:
        text = "---\n{{- if .x }}\nkey: v\n{{- end }}\n---\n# H\n"
        idx = MarkdownDocument(write(tmp_path, text)).get_index()["sections"]
        assert [n["heading"] for n in idx] == ["frontmatter", "H"]

    def test_stray_brace_does_not_disable_yaml_validation(self, tmp_path: Path) -> None:
        text = "---\nname: a\nnote: {{ .x }}\n---\n# H\n"
        p = write(tmp_path, text)
        with pytest.raises(ValueError, match="YAML"):
            MarkdownDocument(p).replace_in_section("frontmatter", "name: a", "name: [")
        assert _bytes(p) == text.encode()

    def test_non_mapping_edit_rejected(self, tmp_path: Path) -> None:
        p = write(tmp_path, AGENT)
        with pytest.raises(ValueError, match="mapping"):
            MarkdownDocument(p).replace_section("frontmatter", "just text")
        assert _bytes(p) == AGENT.encode()

    def test_bad_timestamp_gives_yaml_error(self, tmp_path: Path) -> None:
        p = write(tmp_path, AGENT)
        with pytest.raises(ValueError, match="YAML"):
            MarkdownDocument(p).replace_in_section(
                "frontmatter", "mode: subagent", "mode: 2024-99-99"
            )
        assert _bytes(p) == AGENT.encode()


class TestByteFidelity:
    """replace_section / add_section / delete_section preserve untouched bytes."""

    BASE = "# A\n\nbody a\n\n## B\n\nbody b\n\n## C\n\nbody c\n"

    @pytest.mark.parametrize("tail", ["", "\n", "\n\n\n"])
    def test_trailing_blank_lines_preserved(self, tmp_path: Path, tail: str) -> None:
        text = self.BASE + tail
        p = write(tmp_path, text)
        MarkdownDocument(p).replace_section("A.C", "new c")
        assert _bytes(p) == text.replace("body c", "new c").encode()
        p = write(tmp_path, text, "b.md")
        MarkdownDocument(p).replace_section("A.B", "new b")
        assert _bytes(p) == text.replace("body b", "new b").encode()
        p = write(tmp_path, text, "c.md")
        MarkdownDocument(p).delete_section("A.B")
        assert _bytes(p) == text.replace("## B\n\nbody b\n\n", "").encode()

    @pytest.mark.parametrize("tail", ["", "\n", "\n\n\n"])
    def test_add_section_before_keeps_tail(self, tmp_path: Path, tail: str) -> None:
        text = self.BASE + tail
        p = write(tmp_path, text)
        MarkdownDocument(p).add_section("## X", "x", before="A.C")
        assert _bytes(p) == text.replace("## C", "## X\n\nx\n\n## C").encode()

    def test_add_section_at_end_no_extra_blank(self, tmp_path: Path) -> None:
        p = write(tmp_path, "# A\n\nx\n")
        MarkdownDocument(p).add_section("## B", "y")
        assert _bytes(p) == b"# A\n\nx\n\n## B\n\ny\n"

    def test_delete_last_section_trims_separator(self, tmp_path: Path) -> None:
        p = write(tmp_path, self.BASE)
        MarkdownDocument(p).delete_section("A.C")
        assert _bytes(p) == b"# A\n\nbody a\n\n## B\n\nbody b\n"

    def test_delete_does_not_touch_distant_blank_runs(self, tmp_path: Path) -> None:
        text = "# A\n\nx\n\n## B\n\ny\n\n## C\n\nz\n\n\n\nw\n"
        p = write(tmp_path, text)
        MarkdownDocument(p).delete_section("A.B")
        assert _bytes(p) == b"# A\n\nx\n\n## C\n\nz\n\n\n\nw\n"

    def test_crlf_replace_add_delete(self, tmp_path: Path) -> None:
        text = self.BASE.replace("\n", "\r\n")
        p = write(tmp_path, text)
        MarkdownDocument(p).replace_section("A.B", "new b\nline2")
        assert _bytes(p) == text.replace("body b", "new b\r\nline2").encode()
        p = write(tmp_path, text, "b.md")
        MarkdownDocument(p).add_section("## X", "x", after="A.B")
        assert _bytes(p) == text.replace("## C", "## X\r\n\r\nx\r\n\r\n## C").encode()
        p = write(tmp_path, text, "c.md")
        MarkdownDocument(p).delete_section("A.B")
        assert _bytes(p) == text.replace("## B\r\n\r\nbody b\r\n\r\n", "").encode()

    def test_crlf_without_trailing_newline_last_section(self, tmp_path: Path) -> None:
        text = "# A\r\n\r\nold"
        p = write(tmp_path, text)
        MarkdownDocument(p).replace_section("A", "new")
        assert _bytes(p) == b"# A\r\n\r\nnew"

    def test_mixed_endings_preserved_outside_edit(self, tmp_path: Path) -> None:
        text = "# A\r\n\r\nkeep1\n\n## B\n\nold\n\n## C\r\n\r\nkeep2\r\n"
        p = write(tmp_path, text)
        MarkdownDocument(p).replace_section("A.B", "new")
        assert _bytes(p) == text.replace("old", "new").encode()
        p = write(tmp_path, text, "b.md")
        MarkdownDocument(p).delete_section("A.B")
        assert _bytes(p) == b"# A\r\n\r\nkeep1\n\n## C\r\n\r\nkeep2\r\n"

    def test_lone_cr_bytes_preserved(self, tmp_path: Path) -> None:
        text = "# A\n\nline\rwith cr\n\n## B\n\nold\n"
        p = write(tmp_path, text)
        MarkdownDocument(p).replace_section("A.B", "new")
        assert _bytes(p) == text.replace("old", "new").encode()

    def test_replace_section_frontmatter_crlf(self, tmp_path: Path) -> None:
        text = AGENT.replace("\n", "\r\n")
        p = write(tmp_path, text)
        MarkdownDocument(p).replace_section("frontmatter", "description: X\nmode: y")
        assert (
            _bytes(p)
            == text.replace(
                "description: Reviews code\r\nmode: subagent",
                "description: X\r\nmode: y",
            ).encode()
        )

    def test_patch_section_matches_replace_section(self, tmp_path: Path) -> None:
        text = self.BASE + "\n\n"
        p = write(tmp_path, text)
        diff = MarkdownDocument(p).patch_section("A.C", "new c")
        assert "-body c" in diff and "+new c" in diff
        assert "\n+\n" not in diff.replace("+++", "")  # no phantom blank line
        assert _bytes(p) == text.encode()


class TestLineSplitting:
    @pytest.mark.parametrize("sep", ["\x0c", "\u2028", "\x0b", "\x85", "\u2029"])
    def test_exotic_separators_do_not_misalign(self, tmp_path: Path, sep: str) -> None:
        text = f"# A\n\nx{sep}y\n\n## B\n\nz\n"
        p = write(tmp_path, text)
        doc = MarkdownDocument(p)
        assert doc.get_section("A.B") == "## B\n\nz"
        assert doc.search_sections("^z$")[0]["matches"][0]["line"] == 7
        doc.replace_in_section("A.B", "z", "w")
        assert _bytes(p) == text.replace("z\n", "w\n").encode()
        doc.replace_section("A", "x" + sep + "y2")
        assert _bytes(p) == text.replace("y\n", "y2\n").replace("z\n", "w\n").encode()


class TestUnbalancedTemplate:
    def test_unbalanced_open_brace_in_prose(self, tmp_path: Path) -> None:
        text = "# A\n\nuse {{ for templates\n\n## B\n\nbody\n\n## C\n\nend }}\n"
        idx = MarkdownDocument(write(tmp_path, text)).get_index()["sections"]
        assert [c["heading"] for c in idx[0]["children"]] == ["B", "C"]

    def test_brace_in_code_fence_not_a_template(self, tmp_path: Path) -> None:
        text = "# A\n\n```\n{{\n```\n\n## B\n\n```\n}}\n```\n"
        idx = MarkdownDocument(write(tmp_path, text)).get_index()["sections"]
        assert [c["heading"] for c in idx[0]["children"]] == ["B"]

    def test_long_action_not_swallowed(self, tmp_path: Path) -> None:
        mid = "\n".join(f"l{i}" for i in range(40))
        text = f"# A\n\n{{{{ start\n{mid}\n## B\n}}}}\n"
        idx = MarkdownDocument(write(tmp_path, text)).get_index()["sections"]
        assert [c["heading"] for c in idx[0]["children"]] == ["B"]


class TestReplaceInSectionCrlf:
    def test_multiline_old_with_lf_matches_crlf_file(self, tmp_path: Path) -> None:
        text = "# A\r\n\r\nline1\r\nline2\r\nline3\r\n"
        p = write(tmp_path, text)
        MarkdownDocument(p).replace_in_section("A", "line1\nline2", "L1\nL2\nL2b")
        assert _bytes(p) == b"# A\r\n\r\nL1\r\nL2\r\nL2b\r\nline3\r\n"


class TestSearchFilesHardening:
    def test_symlink_escape_skipped(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside"
        inside = tmp_path / "inside"
        outside.mkdir()
        inside.mkdir()
        write(outside, "# S\n\nsecret phrase\n", "s.md")
        (inside / "link.md").symlink_to(outside / "s.md")
        write(inside, "# O\n\nsecret phrase ok\n", "ok.md")
        res = server.search_files(str(inside), "*.md", "secret phrase")
        assert [Path(m["file_path"]).name for m in res["matches"]] == ["ok.md"]
        assert res["skipped"] == 1

    @pytest.mark.parametrize("glob", ["../*.md", "sub/../../*.md", "/etc/*"])
    def test_escaping_glob_rejected(self, tmp_path: Path, glob: str) -> None:
        d = tmp_path / "d"
        d.mkdir()
        write(tmp_path, "# X\n\nphrase\n", "x.md")
        with pytest.raises(ValueError):
            server.search_files(str(d), glob, "phrase")

    def test_size_cap_and_text_truncation(self, tmp_path: Path) -> None:
        write(tmp_path, "# A\n\n" + "phrase " + "x" * 1000 + "\n", "big.md")
        res = server.search_files(str(tmp_path), "*.md", "phrase")
        assert len(res["matches"][0]["text"]) == 300
        res = server.search_files(str(tmp_path), "*.md", "phrase", max_file_bytes=100)
        assert res["matches"] == [] and res["skipped"] == 1

    def test_limit_hard_maximum(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            server.search_files(str(tmp_path), "*.md", "x", limit=1001)
        assert "matches" in server.search_files(str(tmp_path), "*.md", "x", limit=1000)
