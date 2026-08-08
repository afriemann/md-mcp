# tools Specification

## Purpose

Defines the seven MCP tools exposed by the md-mcp server for reading, navigating, searching, and editing Markdown documents by section address. All tools accept `file_path` as an absolute filesystem path and identify sections via a dot-separated `path` string derived from heading text (case-insensitive). Literal dots in headings are escaped as `\.` in path strings.
## Requirements
### Requirement: get_index returns the section tree

The `get_index` tool SHALL return a nested tree of all sections in a Markdown file. Each node SHALL contain the section heading text, nesting level, dot-separated path address, and a list of child nodes.

#### Scenario: Returns nested section tree

- **GIVEN** a Markdown file with multiple heading levels
- **WHEN** `get_index` is called with a valid file path
- **THEN** the response contains a nested tree where each node has `heading`, `level`, `path`, and `children` fields

### Requirement: get_section returns section content by path

The `get_section` tool SHALL return the heading line and body text of the section identified by the dot-separated path address. The `depth` parameter SHALL control how many levels of child sections are included (default: all descendants).

#### Scenario: Returns section content at given path

- **GIVEN** a Markdown file with a known section hierarchy
- **WHEN** `get_section` is called with a valid dot-separated path
- **THEN** the response contains that section's heading and body text

#### Scenario: depth=0 returns only the section body without children

- **GIVEN** a Markdown file with a section that has child sections
- **WHEN** `get_section` is called with `depth=0`
- **THEN** the response contains only the heading and body of the named section, with no child section content

### Requirement: search_sections finds body text by regex

The `search_sections` tool SHALL search each section's own body text (excluding heading text) for lines matching a Python regular expression. It SHALL return one result per matching section, each containing the section path and the matched lines with their 1-based file line numbers.

#### Scenario: Finds matching text in section bodies

- **GIVEN** a Markdown file with known section content
- **WHEN** `search_sections` is called with a regex matching text in a section body
- **THEN** the response lists the matching section path, the matched line text, and the 1-based line number

#### Scenario: Does not search heading text

- **GIVEN** a Markdown file where a regex matches only a section heading, not its body
- **WHEN** `search_sections` is called with that regex
- **THEN** the response is empty (no matches)

### Requirement: add_section inserts a new section

The `add_section` tool SHALL insert a new section heading and body into the Markdown file at the specified placement position: as the last child of an existing section (`under`), immediately before an existing section (`before`), immediately after an existing section and all its children (`after`), or appended at the end when no placement is specified.

#### Scenario: Appends a new section when no placement is given

- **GIVEN** a Markdown file
- **WHEN** `add_section` is called with a valid heading and content and no placement arguments
- **THEN** the new section appears at the end of the file and the tool returns "ok"

#### Scenario: Inserts a section before an existing one

- **GIVEN** a Markdown file with a known section
- **WHEN** `add_section` is called with `before` set to that section's path
- **THEN** the new section appears immediately before the named section in the file

### Requirement: replace_section updates a section body

The `replace_section` tool SHALL replace the body text of the section identified by the dot-separated path address, preserving the section's heading line unchanged.

#### Scenario: Replaces section body while preserving heading

- **GIVEN** a Markdown file with a known section
- **WHEN** `replace_section` is called with a valid path and new body content
- **THEN** the section's body is updated to the new content and its heading line is unchanged

### Requirement: patch_section returns a dry-run diff

The `patch_section` tool SHALL return a unified diff showing what `replace_section` would change, without writing to the file. An empty string SHALL be returned when the proposed content is identical to the current section body.

#### Scenario: Returns a diff without modifying the file

- **GIVEN** a Markdown file with a known section
- **WHEN** `patch_section` is called with a valid path and changed content
- **THEN** a non-empty unified diff is returned and the file is not modified

#### Scenario: Returns empty string when content is unchanged

- **GIVEN** a Markdown file with a known section
- **WHEN** `patch_section` is called with content identical to the current section body
- **THEN** an empty string is returned

### Requirement: delete_section removes a section

The `delete_section` tool SHALL remove the section identified by the dot-separated path address from the Markdown file. With `include_children=True` (the default), all child sections SHALL also be removed. With `include_children=False`, only the named section's heading and body SHALL be removed and its child sections SHALL be promoted to the parent level.

#### Scenario: Deletes section with all children

- **GIVEN** a Markdown file with a section containing child sections
- **WHEN** `delete_section` is called with the default `include_children=True`
- **THEN** the named section and all its child sections are removed from the file

#### Scenario: Deletes section body only, promoting children

- **GIVEN** a Markdown file with a section containing child sections
- **WHEN** `delete_section` is called with `include_children=False`
- **THEN** the named section's heading and body are removed, and its child sections remain at the parent level

### Requirement: get_index description identifies it as the required entry point

The `get_index` tool description SHALL open with an instruction stating that it must be called first before any other tool that accepts a `path` parameter. It SHALL name the path-dependent tools explicitly so agents understand the dependency.

#### Scenario: Description communicates get_index as prerequisite

- **WHEN** an agent reads the `get_index` tool description
- **THEN** the description contains a clear instruction to call `get_index` first, and names the tools that depend on its output for valid `path` values

### Requirement: Path-dependent tool descriptions reference get_index as path source

The descriptions for `get_section`, `search_sections`, `add_section`, `replace_section`, `patch_section`, and `delete_section` SHALL each state that valid `path` values are obtained from `get_index`.

#### Scenario: get_section description names get_index as path source

- **WHEN** an agent reads the `get_section` tool description
- **THEN** the description states that the `path` argument must be obtained from `get_index`

#### Scenario: Mutating tool descriptions name get_index as path source

- **WHEN** an agent reads the description for `add_section`, `replace_section`, `patch_section`, or `delete_section`
- **THEN** each description states that `path` values come from `get_index`

### Requirement: replace_section description references patch_section as the recommended pre-write step

The `replace_section` tool description SHALL reference `patch_section` as the recommended dry-run preview step to call before writing. The `patch_section` description SHALL explicitly instruct agents to call it before `replace_section`, not merely describe it as useful.

#### Scenario: replace_section description contains workflow guidance

- **WHEN** an agent reads the `replace_section` tool description
- **THEN** the description references `patch_section` and describes the recommended call sequence: preview with `patch_section`, then commit with `replace_section`

#### Scenario: patch_section description instructs calling it before replace_section

- **WHEN** an agent reads the `patch_section` tool description
- **THEN** the description opens with an instruction to call it before `replace_section`, not a passive description of its function

### Requirement: Mutating tool descriptions signal preference over generic file-write tools

The descriptions for `add_section`, `replace_section`, and `delete_section` SHALL each contain a signal that the tool is preferred over generic `edit`/`write` file tools when the Markdown file has section structure.

#### Scenario: replace_section description signals structured-tool preference

- **WHEN** an agent reads the `replace_section` tool description
- **THEN** the description contains a statement indicating it should be used instead of generic file-write tools for structured Markdown files

### Requirement: search_sections description promotes the heading exclusion caveat

The `search_sections` tool description SHALL state the heading-exclusion caveat (heading text is not searched — only section bodies) before the response schema, and SHALL state that `case_sensitive` defaults to `False` (case-insensitive matching).

#### Scenario: Heading-exclusion caveat is visible before the response schema

- **WHEN** an agent reads the `search_sections` tool description
- **THEN** the caveat that heading text is not searched appears before the response schema in the description

#### Scenario: case_sensitive default is stated in prose

- **WHEN** an agent reads the `search_sections` tool description
- **THEN** the description explicitly states that matching is case-insensitive by default

### Requirement: add_section description distinguishes it from replace_section

The `add_section` tool description SHALL open with a statement that it is used for sections that do not yet exist, and SHALL note that `replace_section` is the correct tool for updating an existing section's body.

#### Scenario: Description communicates when to use add_section vs replace_section

- **WHEN** an agent reads the `add_section` tool description
- **THEN** the description states it is for inserting new sections and directs agents to `replace_section` for updating existing sections

### Requirement: delete_section description distinguishes it from replace_section

The `delete_section` tool description SHALL note that it is for removing a section entirely (heading and body), and SHALL distinguish this from `replace_section` with empty content (which keeps the heading).

#### Scenario: Description communicates when to use delete_section vs replace_section

- **WHEN** an agent reads the `delete_section` tool description
- **THEN** the description states that it removes the heading and body together, and notes that `replace_section` with empty content is the alternative when only the body should be cleared

