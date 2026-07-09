"""Tests for graceful SIGTERM shutdown behaviour.

Spec: openspec/changes/graceful-sigterm-handler/specs/server-lifecycle/spec.md

Scenarios:
  1. SIGTERM while idle → exits with code 0 within 2 s
  2. SIGTERM during in-flight operation → finally blocks run before exit
  3. stdin EOF (normal path) → exits within 2 s (regression guard)
"""

from __future__ import annotations

import pathlib
import select
import signal
import subprocess
import sys
import textwrap
import time

import pytest


def _spawn_server() -> subprocess.Popen[bytes]:
    """Spawn the md-mcp server as a subprocess using the active Python interpreter.

    Using ``sys.executable -c "from md_mcp.server import main; main()"`` ensures
    we run exactly the package under test, regardless of PATH or script install
    location.
    """
    return subprocess.Popen(
        [sys.executable, "-c", "from md_mcp.server import main; main()"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _wait_for_marker(
    proc: subprocess.Popen[bytes],
    marker: bytes,
    timeout: float = 5.0,
) -> None:
    """Block until ``marker`` appears in the process's stderr stream.

    Raises ``pytest.fail`` if the marker does not appear within *timeout*
    seconds or if the process exits unexpectedly before it is seen.
    """
    deadline = time.monotonic() + timeout
    buf = b""
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        r, _, _ = select.select([proc.stderr], [], [], min(remaining, 0.2))
        if not r:
            continue
        assert proc.stderr is not None
        chunk = proc.stderr.read1(4096)  # type: ignore[attr-defined]
        buf += chunk
        if marker in buf:
            return
        if proc.poll() is not None:
            pytest.fail(
                f"Process exited unexpectedly (code={proc.poll()}) "
                f"before marker {marker!r} was seen"
            )
    pytest.fail(f"Process did not emit marker {marker!r} within {timeout} s")


def _wait_server_up(proc: subprocess.Popen[bytes], timeout: float = 5.0) -> None:
    """Block until the server's SIGTERM signal handler is fully installed.

    The server prints ``SIGTERM-handler-ready`` to stderr from *inside*
    ``_run_with_graceful_shutdown``, immediately after
    ``anyio.open_signal_receiver`` registers the OS-level handler.  Waiting for
    this marker (rather than the earlier WARNING log line + a fixed sleep)
    eliminates the race where SIGTERM arrives before the handler is registered.
    """
    _wait_for_marker(proc, b"SIGTERM-handler-ready", timeout=timeout)


class TestSigtermShutdown:
    """Server gracefully handles SIGTERM (spec: server-lifecycle)."""

    def test_sigterm_while_idle_exits_with_code_zero(self) -> None:
        """GIVEN a running idle server WHEN SIGTERM is sent THEN it exits with code 0 within 2 s."""
        proc = _spawn_server()
        try:
            _wait_server_up(proc)
            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                pytest.fail("Server did not exit within 2 seconds after SIGTERM")
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()

        assert proc.returncode == 0, (
            f"Expected exit code 0 after graceful SIGTERM shutdown, got {proc.returncode}"
        )

    def test_sigterm_during_inflight_operation_runs_finally_blocks(
        self, tmp_path: pathlib.Path
    ) -> None:
        """GIVEN an in-flight operation with a finally block
        WHEN SIGTERM is sent while the operation is executing
        THEN the finally block runs before the process exits (exit code 0).

        Uses an inline subprocess that replicates the cooperative-cancellation
        pattern of _run_with_graceful_shutdown with a simulated slow operation
        whose finally block writes a sentinel file.
        """
        sentinel = tmp_path / "finally_ran.sentinel"

        # Inline script: mirrors _run_with_graceful_shutdown exactly, with a
        # slow in-flight coroutine whose finally block writes the sentinel.
        script = textwrap.dedent(f"""
            import asyncio, anyio, os, pathlib, signal, sys

            sentinel = pathlib.Path({str(sentinel)!r})

            async def _run() -> None:
                with anyio.open_signal_receiver(signal.SIGTERM) as sigterm:
                    print("SIGTERM-handler-ready", file=sys.stderr, flush=True)
                    async with anyio.create_task_group() as tg:

                        async def _in_flight_with_finally() -> None:
                            try:
                                await anyio.sleep(10.0)  # simulate slow tool call
                            finally:
                                sentinel.write_text("finally ran")

                        async def _watch_sigterm() -> None:
                            async for _ in sigterm:
                                async def _force_exit() -> None:
                                    await asyncio.sleep(1.0)
                                    os._exit(0)
                                asyncio.create_task(_force_exit())
                                tg.cancel_scope.cancel()
                                return

                        tg.start_soon(_in_flight_with_finally)
                        tg.start_soon(_watch_sigterm)

            anyio.run(_run)
        """)

        proc = subprocess.Popen(
            [sys.executable, "-c", script],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            _wait_for_marker(proc, b"SIGTERM-handler-ready")
            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                pytest.fail("Process did not exit within 2 seconds after SIGTERM")
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()

        assert proc.returncode == 0, (
            f"Expected exit code 0 after graceful SIGTERM, got {proc.returncode}"
        )
        assert sentinel.exists(), (
            "Sentinel file not written — finally block did not run before process exit"
        )

    def test_stdin_eof_exits_within_two_seconds(self) -> None:
        """GIVEN a running server WHEN stdin is closed THEN it exits within 2 s (regression guard)."""
        proc = _spawn_server()
        try:
            _wait_server_up(proc)
            assert proc.stdin is not None
            proc.stdin.close()
            try:
                proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                pytest.fail("Server did not exit within 2 seconds after stdin EOF")
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
