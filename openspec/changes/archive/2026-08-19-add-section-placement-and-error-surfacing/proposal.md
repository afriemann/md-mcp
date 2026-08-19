## Why

Two usability issues were reported during real agent use. First, `add_section` rejects the intuitive `under + before/after` combination with a generic error, even though the combination is semantically valid (`under` names the parent; `before`/`after` names the sibling position). Second, all tools return `"Error: ..."` strings on failure, so the opencode TUI shows a successful tool call even when the operation failed — agents and operators cannot distinguish success from error in the call history.

## What Changes

- `add_section` accepts `under` alongside `before` or `after` as a redundant-but-valid parent confirmation. When the combination is supplied, `under` is validated against the parent implied by the sibling path and then stripped; if they disagree, a clear error is raised.
- `before + after` together (contradictory sibling anchors) remains an error.
- All seven MCP tools stop catching domain exceptions (`FileNotFoundError`, `PermissionError`, `KeyError`, `ValueError`, `OSError`, `re.error`). Exceptions propagate to `MCPServer._handle_call_tool`, which wraps them in `CallToolResult(is_error=True)` — surfacing them as failed tool calls in the opencode TUI.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `tools`: two requirement changes — `add_section` placement validation is relaxed; all tools now surface errors as protocol-level failures (`is_error=True`) rather than as success responses containing error text.

## Impact

- `src/md_mcp/document.py` — `add_section` validation logic
- `src/md_mcp/server.py` — remove all `try/except` from tool functions; update `add_section` docstring
- `tests/test_document.py` — new cases for `under+before/after` combinations
- `tests/test_server.py` (or integration tests) — new cases verifying `is_error=True` on tool failure
