## Why

When the MCP server is stopped via SIGTERM (the standard signal used by MCP
clients and process managers), the current handler is `SIG_DFL` — the process
terminates immediately at the C level with no async cleanup. Any in-flight tool
call that is partway through a file write is cut off without completing. Adding
a graceful handler converts SIGTERM into a cooperative anyio task-group
cancellation, giving in-flight calls a chance to run their `finally` blocks
before the process exits.

## What Changes

- Replace `mcp.run(transport="stdio")` in `main()` with `anyio.run(_run_with_graceful_shutdown)`.
- `_run_with_graceful_shutdown()` wraps `mcp.run_stdio_async()` in an anyio task group alongside a SIGTERM watcher that cancels the scope on signal arrival.
- Normal exit path (stdin EOF) is preserved: when `run_stdio_async` returns, the watcher task is also cancelled so the process exits cleanly.
- SIGTERM now causes the process to exit via cooperative cancellation rather than immediate termination.

## Capabilities

### New Capabilities

- `server-lifecycle`: How the MCP server process starts, handles termination signals, and shuts down.

### Modified Capabilities

<!-- None — no existing specs exist yet; the new spec above covers current and new behaviour. -->

## Impact

- `src/md_mcp/server.py` — `main()` function only; no tool handler changes.
- `tests/test_server.py` — new process-level test for SIGTERM behaviour.
- New runtime dependency: `anyio` (already a transitive dependency via `mcp`).
