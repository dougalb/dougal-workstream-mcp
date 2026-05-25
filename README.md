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

HTTP MCP is mounted at `http://localhost:8000/mcp`. The healthcheck is `http://localhost:8000/healthz`.

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
- `record_decision`
- `record_task`
- `record_codex_session`
- `search_workstream`

Example CLI capture:

```bash
workstream capture --file examples/handoff.json --source chatgpt --project dougal-workstream-mcp
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
- Health: `http://localhost:8000/healthz`

To run stdio mode inside the container:

```bash
docker compose run --rm workstream-mcp workstream serve --transport stdio
```

## OpenClaw Consumption

OpenClaw can consume this later in two ways:

- as an MCP client reading `workstream://projects`, `workstream://recent`, and project resources directly.
- through a small CLI/API bridge that shells out to `workstream recent`, `workstream list-tasks`, or queries the SQLite database read-only.

For v0.1, no public internet exposure is implemented.

## Security Model

This server is local-first and stores only local SQLite data. It rejects write inputs that look like API keys, passwords, tokens, private keys, OAuth secrets, bearer tokens, JWTs, common provider tokens, or high-entropy secret strings.

Allowed secret references:

- `1password://...`
- `op://...`
- `vault://...`

Limitations:

- Secret detection is conservative but not perfect.
- There is no multi-user auth model in v0.1.
- HTTP mode is intended for trusted local/container networks only.
- Markdown exports inherit the sensitivity of stored content and should be treated as local working files.
