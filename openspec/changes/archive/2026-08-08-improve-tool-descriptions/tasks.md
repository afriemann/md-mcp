## 1. Rewrite tool docstrings in server.py

- [ ] 1.1 Rewrite `get_index` docstring — open with "Call this first" instruction, list all path-dependent tools by name, retain path format details
- [ ] 1.2 Rewrite `get_section` docstring — add one-line prerequisite linking `path` to `get_index`; retain `depth` semantics
- [ ] 1.3 Rewrite `search_sections` docstring — promote heading-exclusion caveat above response schema; state `case_sensitive=False` default in prose
- [ ] 1.4 Rewrite `add_section` docstring — open with "use for new sections / use replace_section for existing"; note `path` provenance for placement params
- [ ] 1.5 Rewrite `replace_section` docstring — open with "prefer over generic file-write" signal; document `patch_section`→`replace_section` workflow; document all parameters
- [ ] 1.6 Rewrite `patch_section` docstring — open with "Call this before replace_section"; document parameters; retain empty-string = no-change note
- [ ] 1.7 Rewrite `delete_section` docstring — distinguish from `replace_section` (heading is also removed); note `path` provenance

## 2. Verify

- [ ] 2.1 Run existing test suite (`uv run pytest`) — confirm zero regressions
- [ ] 2.2 Run linter (`uv run ruff check src/ tests/`) — confirm no new violations

Note: Automated tests for docstring content are not added — testing specific phrases in docstrings would assert implementation detail rather than observable behaviour, which is prohibited by the project's right-sized-tests rule. The scenarios in the delta spec serve as the human-reviewable contract verified by code review.
