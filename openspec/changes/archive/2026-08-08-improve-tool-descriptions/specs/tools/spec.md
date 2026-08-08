## ADDED Requirements

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
