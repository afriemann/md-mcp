"""Tests for md_mcp.server path-guard logic (_check_path and _allowed_roots)."""

from __future__ import annotations

import pathlib

import pytest

import md_mcp.server as server_module
from md_mcp.server import _check_path


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
