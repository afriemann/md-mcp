"""Tests for md_mcp.server path-guard logic (_check_path and _allowed_roots)."""

from __future__ import annotations

import pathlib

import pytest
from mcp.server.mcpserver.exceptions import ToolError

import md_mcp.server as server_module
from md_mcp.server import _check_path, mcp


class TestCheckPathExpandsUser:
    """_check_path must expand ~ so tilde paths work correctly."""

    def test_tilde_in_file_path_does_not_contain_literal_tilde(self) -> None:
        """_check_path('~/some/file.md') must return a path without a literal ~."""
        resolved = _check_path("~/some/file.md")
        assert "~" not in str(resolved), (
            f"Resolved path should not contain '~', got: {resolved}"
        )

    def test_tilde_resolves_to_home_subtree(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        """_check_path('~/foo') must resolve under the HOME directory."""

        monkeypatch.setenv("HOME", str(tmp_path))

        resolved = _check_path("~/foo")
        # The resolved path should be under tmp_path (our patched home)
        assert str(resolved).startswith(str(tmp_path)), (
            f"Expected path under {tmp_path}, got: {resolved}"
        )

    def test_allowed_roots_tilde_accepted(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        """When _allowed_roots contains a tilde root, a file under it must pass."""
        monkeypatch.setenv("HOME", str(tmp_path))

        # Build the allowed-root list the same way main() does (after the fix)
        allowed_root = pathlib.Path("~/allowed").expanduser().resolve()
        original_roots = server_module._allowed_roots
        try:
            server_module._allowed_roots = [allowed_root]

            # A file under that root should not raise PermissionError
            resolved = _check_path("~/allowed/doc.md")
            assert "~" not in str(resolved)
        finally:
            server_module._allowed_roots = original_roots

    def test_disallowed_path_raises_permission_error(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        """A file outside all allowed roots must raise PermissionError."""
        monkeypatch.setenv("HOME", str(tmp_path))

        allowed_root = pathlib.Path("~/allowed").expanduser().resolve()
        original_roots = server_module._allowed_roots
        try:
            server_module._allowed_roots = [allowed_root]

            with pytest.raises(
                PermissionError, match="path not under any allowed root"
            ):
                _check_path("~/other/doc.md")
        finally:
            server_module._allowed_roots = original_roots


# ---------------------------------------------------------------------------
# Tool error surfacing — tools must raise, not return "Error: ..." strings
# spec: openspec/changes/add-section-placement-and-error-surfacing/specs/tools/spec.md
# ---------------------------------------------------------------------------


class TestToolErrorSurfacing:
    """MCP tools must propagate exceptions so MCPServer marks the call is_error=True."""

    async def test_get_section_raises_on_missing_file(
        self, tmp_path: pathlib.Path
    ) -> None:
        """get_section raises (ToolError wrapping FileNotFoundError) for a non-existent file."""
        with pytest.raises(ToolError, match="No such file|nonexistent"):
            await mcp.call_tool(
                "get_section",
                {"file_path": str(tmp_path / "nonexistent.md"), "path": "Root"},
            )

    async def test_get_section_raises_on_invalid_path(
        self, tmp_path: pathlib.Path
    ) -> None:
        """get_section raises (ToolError wrapping KeyError) when section path is not found."""
        md = tmp_path / "doc.md"
        md.write_text("# Root\n\nContent\n", encoding="utf-8")
        with pytest.raises(ToolError, match="NonExistent"):
            await mcp.call_tool(
                "get_section",
                {"file_path": str(md), "path": "Root.NonExistent"},
            )

    async def test_add_section_raises_on_missing_file(
        self, tmp_path: pathlib.Path
    ) -> None:
        """add_section raises (ToolError wrapping FileNotFoundError) for a non-existent file."""
        with pytest.raises(ToolError, match="No such file|nonexistent"):
            await mcp.call_tool(
                "add_section",
                {
                    "file_path": str(tmp_path / "nonexistent.md"),
                    "heading": "## New",
                    "content": "body",
                },
            )

    async def test_get_index_raises_on_missing_file(
        self, tmp_path: pathlib.Path
    ) -> None:
        """get_index raises (ToolError wrapping FileNotFoundError) for a non-existent file."""
        with pytest.raises(ToolError, match="No such file|nonexistent"):
            await mcp.call_tool(
                "get_index",
                {"file_path": str(tmp_path / "nonexistent.md")},
            )

    async def test_search_sections_raises_on_missing_file(
        self, tmp_path: pathlib.Path
    ) -> None:
        """search_sections raises (ToolError wrapping FileNotFoundError) for a non-existent file."""
        with pytest.raises(ToolError, match="No such file|nonexistent"):
            await mcp.call_tool(
                "search_sections",
                {
                    "file_path": str(tmp_path / "nonexistent.md"),
                    "query": "foo",
                },
            )

    async def test_delete_section_raises_on_missing_file(
        self, tmp_path: pathlib.Path
    ) -> None:
        """delete_section raises (ToolError wrapping FileNotFoundError) for a non-existent file."""
        with pytest.raises(ToolError, match="No such file|nonexistent"):
            await mcp.call_tool(
                "delete_section",
                {
                    "file_path": str(tmp_path / "nonexistent.md"),
                    "path": "Root",
                },
            )

    async def test_tool_raises_on_disallowed_path(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        """Tools raise ToolError (wrapping PermissionError) for paths outside allowed roots."""
        allowed_root = tmp_path / "allowed"
        allowed_root.mkdir()
        original_roots = server_module._allowed_roots
        try:
            server_module._allowed_roots = [allowed_root]
            with pytest.raises(ToolError, match="not under any allowed root"):
                await mcp.call_tool(
                    "get_section",
                    {
                        "file_path": str(tmp_path / "outside.md"),
                        "path": "Root",
                    },
                )
        finally:
            server_module._allowed_roots = original_roots
