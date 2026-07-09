## 1. Tests (red step)

- [ ] 1.1 Add `test_sigterm_exits_cleanly` — spawn the server, send SIGTERM, assert exit within 2 s with code 0
- [ ] 1.2 Add `test_stdin_eof_exits_cleanly` — spawn the server, close stdin, assert exit within 2 s with code 0 (regression guard)

## 2. Implementation

- [ ] 2.1 Add `import anyio` and `import signal` to `server.py`
- [ ] 2.2 Add `_run_with_graceful_shutdown()` async function: wraps `mcp.run_stdio_async()` in an anyio task group with `asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, ...)` cancelling the scope on arrival; `finally` in the server task cancels the scope on normal exit
- [ ] 2.3 Replace `mcp.run(transport="stdio")` with `anyio.run(_run_with_graceful_shutdown)` in `main()`

## 3. Verify

- [ ] 3.1 Run full test suite; all tests green
- [ ] 3.2 Run linter/type-checker; no new errors
