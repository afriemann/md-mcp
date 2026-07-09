## ADDED Requirements

### Requirement: Server exits gracefully on SIGTERM
The server process SHALL respond to SIGTERM by cooperatively cancelling the
anyio task group, allowing in-flight tool calls to complete their `finally`
blocks, and exiting with status code 0 within a reasonable timeout.

#### Scenario: SIGTERM triggers clean shutdown
- **WHEN** the server receives SIGTERM while idle (no tool call in progress)
- **THEN** the process exits with status code 0 within 2 seconds

#### Scenario: SIGTERM during in-flight tool call runs finally blocks
- **WHEN** the server receives SIGTERM while a tool call is executing
- **THEN** the tool call's `finally` blocks run before the process exits

#### Scenario: Normal stdin-EOF exit path is preserved
- **WHEN** the server's stdin stream is closed (EOF) without a SIGTERM
- **THEN** the process exits cleanly (status code 0) within 2 seconds without hanging
