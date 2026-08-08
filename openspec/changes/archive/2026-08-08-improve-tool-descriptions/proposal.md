## Why

The seven `@mcp.tool()` docstrings in `server.py` describe what each tool does mechanically but give agents no guidance on when to use them, in what order, or why to prefer them over generic file-write tools. Three recurring gaps cause agents to misuse the API: no tool establishes `get_index` as the mandatory discovery step before any path-dependent call; `replace_section` never points to `patch_section` as the recommended dry-run preview; and no description signals preference over a generic `edit`/`write` tool when working with a structured Markdown file.

## What Changes

- Rewrite the docstring for `get_index` to open with a "call this first" instruction and identify it as the prerequisite for all path-dependent tools.
- Rewrite the docstring for `get_section` to add a one-line prerequisite linking `path` values to `get_index`.
- Rewrite the docstring for `search_sections` to promote the heading-not-searched caveat above the response schema and state the `case_sensitive=False` default in prose.
- Rewrite the docstring for `add_section` to distinguish it from `replace_section` (use this for new sections) and note that placement `path` values come from `get_index`.
- Rewrite the docstring for `replace_section` to open with a "prefer over generic file-write" signal, document the `patch_section`→`replace_section` recommended workflow, and document all parameters.
- Rewrite the docstring for `patch_section` to replace "Useful for" with an explicit "Call this before `replace_section`" instruction and document its parameters.
- Rewrite the docstring for `delete_section` to distinguish it from `replace_section` (use this when the heading must also be removed) and note `path` provenance.

No logic, signatures, or return values are changed.

## Capabilities

### New Capabilities

- `tools`: Document the existing tool API and add requirements for description content — what each tool description must communicate to enable correct proactive agent use.

### Modified Capabilities

<!-- none — tools is a new spec domain -->

## Impact

- `src/md_mcp/server.py` — docstrings only; no logic changes.
- No API contract changes; no new or removed tools; no dependency changes.
