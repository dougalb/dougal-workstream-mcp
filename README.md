# dougal-workstream-mcp

`dougal-workstream-mcp` is a local-first MCP server for sharing project context between ChatGPT, Claude, Codex, Cline, and OpenClaw. It stores handoffs, decisions, tasks, blockers, references, and Codex session summaries in SQLite, then exposes that state as MCP tools, resources, and prompts.

SQLite is the source of truth. Markdown files under `exports/` are generated for human readability.

## Install

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
workstream init
```

Local defaults:

- database: `.workstream/workstream.db`
- exports: `exports/`
- optional config: `/config/workstream.yaml` or `WORKSTREAM_CONFIG_PATH`

Override paths with:

```bash
export WORKSTREAM_DB_PATH=/path/to/workstream.db
export WORKSTREAM_EXPORT_DIR=/path/to/exports
export WORKSTREAM_CONFIG_PATH=/path/to/workstream.yaml
export WORKSTREAM_LOG_DIR=/path/to/logs
export WORKSTREAM_PUBLIC_BASE_URL=http://localhost:8000
export WORKSTREAM_ALLOWED_HOSTS=localhost,localhost:8000,127.0.0.1,127.0.0.1:8000
export WORKSTREAM_TRUST_PROXY_HEADERS=false
```

## Run MCP

Stdio mode:

```bash
workstream serve --transport stdio
```

HTTP mode:

```bash
workstream serve --transport http --host 0.0.0.0 --port 8000
```

HTTP MCP is mounted at `http://localhost:8000/mcp`. SSE compatibility is available at `http://localhost:8000/sse`. Health and readiness checks are available at `http://localhost:8000/healthz` and `http://localhost:8000/readyz`.

## Claude Desktop Example

```json
{
  "mcpServers": {
    "workstream": {
      "command": "/absolute/path/to/.venv/bin/workstream",
      "args": ["serve", "--transport", "stdio"],
      "env": {
        "WORKSTREAM_DB_PATH": "/absolute/path/to/dougal-workstream-mcp/.workstream/workstream.db",
        "WORKSTREAM_EXPORT_DIR": "/absolute/path/to/dougal-workstream-mcp/exports"
      }
    }
  }
}
```

## Tools

- `capture_handoff`
- `record_session_handoff`
- `record_decision`
- `record_chatgpt_decision`
- `record_task`
- `record_openclaw_followup`
- `record_codex_session`
- `record_codex_session_summary`
- `list_recent_changes_since`
- `mark_event_consumed_by_agent`
- `get_agent_digest`
- `create_or_update_project_brief`
- `search_workstream`
- `update_task_status`
- `update_blocker_status`
- `list_projects`
- `list_open_tasks`
- `get_project_brief`

Example CLI capture:

```bash
workstream capture --file examples/handoff.json --source chatgpt --project dougal-workstream-mcp
```

Additional v0.2 CLI commands:

```bash
workstream record-codex-session --file examples/codex-session.json
workstream brief dougal-workstream-mcp
workstream brief dougal-workstream-mcp --format json
workstream update-task 1 --status blocked
workstream update-task 1 --status done
workstream update-blocker 1 --status resolved
workstream doctor
workstream doctor --format json
```

## Resources

- `workstream://today`
- `workstream://projects`
- `workstream://projects/{project_id}`
- `workstream://recent`
- `workstream://tasks/open`
- `workstream://projects/{project_id}/decisions`
- `workstream://projects/{project_id}/tasks`
- `workstream://projects/{project_id}/blockers`

## Prompts

- `chatgpt_handoff`
- `codex_session_summary`
- `project_brief`

Codex should call `record_codex_session` at the end of meaningful work with the repo path, host, goal, status, changed files, commands run, tests summary, decisions, next actions, blockers, and sensitivity. `examples/codex-session.json` shows the intended shape.

For cross-agent coordination, prefer the newer Workstreams-native commands:

- ChatGPT and Claude planning sessions: `record_session_handoff` and `record_chatgpt_decision`.
- Codex implementation sessions: `record_codex_session_summary`.
- OpenClaw follow-up work: `record_openclaw_followup`, `get_agent_digest`, `list_recent_changes_since`, and `mark_event_consumed_by_agent`.
- Project state refreshes: `create_or_update_project_brief`.

See `docs/cross-agent-coordination.md` for the event model, consumption cursor behavior, and example workflows.

## Markdown Export

```bash
workstream export-markdown
```

Generated files:

- `exports/projects/{project_slug}.md`
- `exports/daily/YYYY-MM-DD.md`

## Docker

The image is stateless. Mount persistent data into `/data`, generated Markdown into `/exports`, optional config into `/config/workstream.yaml`, and optional logs into `/logs`.

```bash
docker compose up -d
docker compose logs -f
docker compose exec workstream-mcp workstream init
docker compose exec workstream-mcp workstream recent
docker compose exec workstream-mcp workstream export-markdown
```

Default compose mode runs HTTP MCP on port 8000:

- MCP: `http://localhost:8000/mcp`
- SSE: `http://localhost:8000/sse`
- Health: `http://localhost:8000/healthz`
- Readiness: `http://localhost:8000/readyz`

The compose file binds to `127.0.0.1:8000:8000` by default. Put any public reverse proxy outside this project and forward to the host-local port.

To run stdio mode inside the container:

```bash
docker compose run --rm workstream-mcp workstream serve --transport stdio
```

## OpenClaw Consumption

OpenClaw can consume this in two local-first ways:

- as an MCP client reading `workstream://projects`, `workstream://recent`, and project resources directly.
- through the read-only CLI bridge command `workstream brief PROJECT --format json` or `workstream brief PROJECT`.

For v0.3, the app can sit behind an external HTTPS reverse proxy, but this repo does not manage NGINX or certificates. See `docs/public-proxy-contract.md`.

## ChatGPT Apps SDK Spike

v0.3 adds the first ChatGPT Apps SDK-oriented surface:

- Streamable HTTP at `/mcp`.
- SSE compatibility at `/sse` and `/messages/`.
- OAuth protected-resource metadata at `/.well-known/oauth-protected-resource`.
- Apps SDK-safe tools with `securitySchemes`, output schemas, annotations, structured content, and a minimal `ui://widget/project-brief-v1.html` component resource.

OAuth mode uses an external OAuth/OIDC provider. The app is only a resource server.

```bash
export WORKSTREAM_AUTH_MODE=oauth
export WORKSTREAM_PUBLIC_BASE_URL=https://workstream.example.com
export WORKSTREAM_ALLOWED_HOSTS=workstream.example.com
export WORKSTREAM_TRUST_PROXY_HEADERS=true
export WORKSTREAM_OAUTH_ISSUER=https://auth.example.com
export WORKSTREAM_OAUTH_AUDIENCE=https://workstream.example.com
export WORKSTREAM_OAUTH_JWKS_URL=https://auth.example.com/.well-known/jwks.json
export WORKSTREAM_OAUTH_AUTHORIZATION_URL=https://auth.example.com/oauth2/authorize
export WORKSTREAM_OAUTH_TOKEN_URL=https://auth.example.com/oauth2/token
export WORKSTREAM_OAUTH_CLIENT_ID=optional-preconfigured-client-id
```

Scopes:

- `workstream.read`: required for MCP access.
- `workstream.write`: required for write tools.
- `workstream.sensitive`: allows sensitive rows in ChatGPT-facing structured output.

Use `examples/nginx-stack-codex-prompt.md` to steer a separate Codex run that creates the external NGINX stack.

## Security Model

This server is local-first and stores only local SQLite data. It rejects write inputs that look like API keys, passwords, tokens, private keys, OAuth secrets, bearer tokens, JWTs, common provider tokens, or high-entropy secret strings.

Allowed secret references:

- `1password://...`
- `op://...`
- `vault://...`

Limitations:

- Secret detection is conservative but not perfect.
- OAuth mode verifies Bearer JWT signature, issuer, audience/resource, expiry, and scopes on protected MCP paths.
- v0.3 does not implement an OAuth authorization server, multi-tenant hosting, database sync, or public app submission hardening.
- HTTP mode without OAuth is intended for trusted local/container networks only.
- Markdown exports inherit the sensitivity of stored content and should be treated as local working files.


## v0.2 Notes

v0.2 focuses on proving real cross-agent consumption rather than broadening hosting scope. It adds:

- project briefs for OpenClaw/local bridge consumption.
- CLI ingestion of Codex session JSON.
- task status transitions: `open`, `blocked`, `done`.
- blocker status transitions: `open`, `resolved`.
- `workstream doctor` for local diagnostics.
- richer HTTP health/readiness checks.

## v0.3 Notes

v0.3 focuses on ChatGPT Apps SDK compatibility:

- OAuth resource-server mode for public HTTPS deployments behind an external proxy.
- `/sse` compatibility alongside `/mcp`.
- Apps SDK-safe read tools and a minimal project brief widget resource.
- Localhost-only compose port binding by default.
- Public proxy contract documentation and a Codex prompt for creating the separate NGINX stack.
