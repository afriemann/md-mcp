## 1. Tests (TDD red step)

- [x] 1.1 Write failing test: `under + before` inserts before the sibling (same result as `before` alone)
- [x] 1.2 Write failing test: `under + after` inserts after the sibling (same result as `after` alone)
- [x] 1.3 Write failing test: inconsistent `under` (wrong parent) raises `ValueError`
- [x] 1.4 Write failing test: `before + after` together raises `ValueError`
- [x] 1.5 Write failing tests: tool raises on `FileNotFoundError`, `PermissionError`, `KeyError` (is_error=True via in-process MCP client)

## 2. document.py — add_section validation

- [x] 2.1 Replace the single "At most one of under/before/after" guard with: reject `before + after` together; accept `under + before/after` (deferred to post-parse validation)
- [x] 2.2 Add `_parent_path_of(sibling_path)` helper that derives the parent path string from a sibling path using `_split_path` + `_escape_segment`
- [x] 2.3 After headings are parsed, validate `under` against the derived parent: resolve both to indices; raise `ValueError` with the expected parent path if they differ; strip `under` if consistent
- [x] 2.4 Update `add_section` docstring to reflect the relaxed placement rule

## 3. server.py — error surfacing

- [x] 3.1 Remove `try/except` from `get_index` (return dict on success; let exceptions propagate)
- [x] 3.2 Remove `try/except` from `get_section`
- [x] 3.3 Remove `try/except` from `search_sections`
- [x] 3.4 Remove `try/except` from `add_section`; update placement docstring
- [x] 3.5 Remove `try/except` from `replace_section`
- [x] 3.6 Remove `try/except` from `patch_section`
- [x] 3.7 Remove `try/except` from `delete_section`

## 4. Verify

- [x] 4.1 Run `uv run pytest tests/ -q` — all tests pass
- [x] 4.2 Run `uv run ruff format --check src/ tests/` and `uv run ruff check src/ tests/` — no errors
