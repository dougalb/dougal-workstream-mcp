# Codex Session Summary

Project: dougal-workstream-mcp

## What Was Built

- Python package for a local-first MCP workstream server backed by SQLite.
- SQLite schema for projects, events, tasks, decisions, blockers, references, and Codex sessions.
- Core write tools for handoffs, decisions, tasks, Codex sessions, and search.
- MCP resources for projects, recent events, today's events, open tasks, and project-specific decisions/tasks/blockers.
- MCP prompts for ChatGPT handoffs, Codex session summaries, and project briefs.
- CLI commands for init, capture, listing projects/tasks, recent events, serving MCP, and Markdown export.
- Dockerfile, docker-compose.yml, .dockerignore, healthcheck endpoint, and mounted volume layout.
- Example handoff and Codex session JSON files.
- Pytest coverage for database initialization, writes, resources, exports, CLI smoke behavior, Markdown capture parsing, search, and secret rejection.

## What Works

- SQLite is the source of truth.
- Markdown exports are generated under `exports/projects/` and `exports/daily/`.
- Secret-like write inputs are rejected, while `1password://`, `op://`, and `vault://` references are allowed.
- The server supports stdio MCP mode and HTTP MCP mode at `/mcp`.
- HTTP healthcheck is available at `/healthz`.
- Verification passed: 9 unit tests, CLI capture/list/export smoke checks, stdio launch smoke check, HTTP `/healthz` smoke check, Docker Compose config validation, and Docker image build.

## What Is Missing

- Real MCP client validation has not been completed in this session.
- OpenClaw bridge/client behavior is documented but not implemented.
- No public internet exposure, hosted auth, or multi-user permission model exists in v0.1.

## Next Steps

- Exercise stdio mode with Claude Desktop or MCP Inspector.
- Exercise HTTP mode with an MCP client at `http://localhost:8000/mcp`.
- Add a read-only OpenClaw bridge once the desired integration path is clear.


# v0.2 Session Summary

## What Was Built

- Bumped package version to `0.2.0`.
- Added project brief bridge output for local agents: `workstream brief PROJECT` and `workstream brief PROJECT --format json`.
- Added Codex session ingestion command: `workstream record-codex-session --file FILE`.
- Added task status transitions: `open`, `blocked`, `done`.
- Added blocker status transitions: `open`, `resolved`.
- Added MCP tools for task and blocker status updates.
- Added richer `/healthz` plus `/readyz`, backed by database read/write checks.
- Added `workstream doctor` diagnostics in Markdown and JSON.
- Added start-session and end-session example documents.

## Verification

- Syntax check passed with `python3 -m compileall -q src tests`.
- Unit tests passed: 14 tests.
- CLI smoke checks passed for init, capture, Codex session ingestion, brief JSON, status updates, and doctor JSON.
- HTTP smoke checks passed for `/healthz` and `/readyz`.
- Docker Compose config validation passed.
- Docker image build passed for `dougal-workstream-mcp:test`.

## Remaining Gaps

- Real Claude Desktop/MCP Inspector client validation is still manual.
- OpenClaw bridge integration is represented by CLI brief output but no OpenClaw-specific adapter has been added.
- No public exposure, hosted auth, sync engine, or multi-user permission model has been added.


# v0.3 Session Summary

## What Was Built

- Bumped package version to `0.3.0`.
- Added OAuth resource-server configuration and Bearer JWT verification for public deployments behind an external proxy.
- Added unauthenticated `/.well-known/oauth-protected-resource` metadata.
- Added `/sse` and `/messages/` SSE compatibility alongside `/mcp`.
- Added ChatGPT Apps SDK-safe tools: `list_projects`, `list_open_tasks`, `get_project_brief`, and a redacted `search_workstream`.
- Added tool `securitySchemes`, mirrored `_meta.securitySchemes`, output schemas, and required tool annotations.
- Added a minimal Apps SDK component resource at `ui://widget/project-brief-v1.html`.
- Added safe structured-output redaction for sensitive rows, local paths, command history, and secret-like values.
- Updated Docker/Compose defaults for localhost-only port binding and proxy-aware environment variables.
- Added `docs/public-proxy-contract.md` and `examples/nginx-stack-codex-prompt.md` for the external NGINX stack.

## Verification

- Syntax check passed with `python -m compileall src tests` in `/tmp/dougal-workstream-mcp-venv`.
- Unit tests passed: 21 tests.
- Docker Compose config validation passed.
- HTTP smoke checks passed for `/healthz`, `/readyz`, `/.well-known/oauth-protected-resource`, and `/sse`.
- Docker image build passed for `dougal-workstream-mcp:test`.

## Remaining Gaps

- The OAuth provider itself is external and must be configured separately.
- NGINX/certificate automation is intentionally outside this repo.
- ChatGPT developer-mode connection and MCP Inspector OAuth flow still need live validation against the chosen public domain and identity provider.
