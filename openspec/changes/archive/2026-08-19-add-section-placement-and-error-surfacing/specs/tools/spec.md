## MODIFIED Requirements

### Requirement: add_section inserts a new section

The `add_section` tool SHALL insert a new section heading and body into the Markdown file at the specified placement position: as the last child of an existing section (`under`), immediately before an existing section (`before`), immediately after an existing section and all its children (`after`), or appended at the end when no placement is specified.

When `under` is combined with `before` or `after`, the tool SHALL treat `under` as a redundant parent confirmation: it SHALL validate that `under` resolves to the parent section implied by the sibling path, then proceed using only `before` or `after` for placement. If `under` does not match the implied parent, the tool SHALL raise an error naming the expected parent path.

`before` and `after` SHALL NOT be specified together; doing so SHALL raise an error.

#### Scenario: Appends a new section when no placement is given

- **GIVEN** a Markdown file
- **WHEN** `add_section` is called with a valid heading and content and no placement arguments
- **THEN** the new section appears at the end of the file and the tool returns "ok"

#### Scenario: Inserts a section before an existing one

- **GIVEN** a Markdown file with a known section
- **WHEN** `add_section` is called with `before` set to that section's path
- **THEN** the new section appears immediately before the named section in the file

#### Scenario: under + before inserts before the sibling

- **GIVEN** a Markdown file with a parent section containing at least one child section
- **WHEN** `add_section` is called with `under` set to the parent's path and `before` set to the child's path
- **THEN** the new section is inserted immediately before the named child, and the placement is identical to calling with only `before`

#### Scenario: under + after inserts after the sibling

- **GIVEN** a Markdown file with a parent section containing at least one child section
- **WHEN** `add_section` is called with `under` set to the parent's path and `after` set to the child's path
- **THEN** the new section is inserted immediately after the named child (and its descendants), and the placement is identical to calling with only `after`

#### Scenario: under inconsistent with before raises an error

- **GIVEN** a Markdown file with a known section hierarchy
- **WHEN** `add_section` is called with `under` naming a section that is not the parent of the `before` target
- **THEN** the tool raises an error naming the expected parent path

#### Scenario: before and after together raises an error

- **GIVEN** a Markdown file
- **WHEN** `add_section` is called with both `before` and `after` set
- **THEN** the tool raises an error stating that both cannot be specified together

## ADDED Requirements

### Requirement: Tools surface errors as failed tool calls

All seven MCP tools (`get_index`, `get_section`, `search_sections`, `add_section`, `replace_section`, `patch_section`, `delete_section`) SHALL propagate domain exceptions rather than catching them and returning error strings. When a tool raises, the MCP server SHALL mark the call result with `is_error=True` so the caller's TUI distinguishes failure from success.

#### Scenario: File not found surfaces as is_error

- **GIVEN** an MCP client connected to the md-mcp server
- **WHEN** any tool is called with a path to a file that does not exist
- **THEN** the tool call result has `is_error=True` and the error message names the missing file

#### Scenario: Permission denied surfaces as is_error

- **GIVEN** an MCP client connected to the md-mcp server running with restricted roots
- **WHEN** any tool is called with a path outside the allowed roots
- **THEN** the tool call result has `is_error=True`

#### Scenario: Invalid path surfaces as is_error

- **GIVEN** an MCP client connected to the md-mcp server
- **WHEN** a path-dependent tool is called with a path string that does not match any section
- **THEN** the tool call result has `is_error=True` and the error message describes the unresolved path segment
