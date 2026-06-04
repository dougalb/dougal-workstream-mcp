# Cross-Agent Coordination

Workstreams is the durable coordination layer for project state across ChatGPT, Codex, OpenClaw, Claude, Cline, and related agents. Agents should not watch each other's UI or store raw chat transcripts. They should record meaningful semantic events, then consume those events when they need current state.

The intended flow is:

```text
ChatGPT / Codex / OpenClaw / Claude
  -> Workstreams-native commands
  -> structured event log in SQLite
  -> project briefs, tasks, blockers, decisions, references
  -> other agents consume and act
```

SQLite remains the source of truth. Markdown exports are generated views.

## Event Model

The canonical event table is `events`. It stores durable project changes such as:

- `decision`
- `task`
- `task_status`
- `blocker`
- `blocker_status`
- `handoff`
- `session_summary`
- `implementation_note`
- `operational_finding`
- `reference`
- `purchase`
- `architecture_change`
- `project_brief`

Core event fields include project, event type, source, optional source agent, title, summary, body, rationale, next actions, references, sensitivity, related task/decision/blocker IDs, supersession, and metadata JSON.

Keep the event title and summary concise. Put durable rationale, implementation detail, next actions, references, and structured metadata in the dedicated fields. Do not store full chat transcripts by default.

## Events Versus Records

Use an event when something meaningful changed:

- A decision was made.
- A task or blocker was created or changed.
- A session produced durable context for another agent.
- Codex implemented or tested something.
- OpenClaw needs to act on a follow-up.
- A project brief needs a durable update.

Use tasks, decisions, blockers, and references for normalized state that should appear in briefs, open work lists, and search results. High-level commands create both semantic events and linked normalized records where appropriate.

## Sensitivity

Every event and normalized record has a sensitivity value. Supported values are intentionally flexible, but common values are:

- `public`
- `internal`
- `personal`
- `private`
- `secret`

Secret-looking raw values are rejected. Store secret references only, such as `op://...`, `1password://...`, or `vault://...`.

ChatGPT-facing read tools omit sensitive rows unless the caller has `workstream.sensitive`.

## Consumption Model

Agents maintain their own event checkpoints.

`agent_event_consumption` records that an agent consumed an event, with optional notes and action taken.

`agent_project_cursors` records the latest consumed event ID per agent and project.

Repeated calls to `mark_event_consumed_by_agent` are idempotent. Existing consumption rows are kept and optional notes/action text can be filled in.

## Tool Guide

`record_session_handoff`

Use at the end of a meaningful ChatGPT, Claude, Codex, or OpenClaw session. It creates a parent `handoff` event and optional linked decision, task, blocker, and reference events. Duplicate open tasks are linked instead of recreated.

`record_chatgpt_decision`

Use for a specific durable planning or product decision. Exact repeated title/summary pairs are treated as already recorded.

`record_openclaw_followup`

Use when OpenClaw or a named OpenClaw instance should act. It creates an assigned task and a task event.

`list_recent_changes_since`

Use when an agent asks what changed since a timestamp, event ID, or its last consumed checkpoint. When `consumer_agent` is provided and `include_consumed` is false, consumed events are excluded.

`mark_event_consumed_by_agent`

Use after an agent has read and handled events. It records consumption and advances the per-project cursor.

`get_agent_digest`

Use as an agent startup command. It returns unconsumed events, assigned open tasks, open blockers, recent decisions, requested follow-ups, and stale items.

`record_codex_session_summary`

Use at the end of implementation work. It records what changed, files changed, commands/tests run, implementation notes, decisions, blockers, tasks, follow-ups, and references.

`create_or_update_project_brief`

Use to keep current project state readable without reconstructing history. It appends summary deltas rather than blindly overwriting existing brief context.

## Example Workflows

### ChatGPT Planning Handoff

```json
{
  "project": "workstream-e2e-v03",
  "source": "chatgpt",
  "title": "Long-term Workstreams-native command design",
  "summary": "Discussed moving from generic task/decision recording toward native cross-agent coordination commands.",
  "decisions": [
    {
      "title": "Use semantic event capture rather than browser scraping",
      "summary": "Agents should consume structured Workstreams events instead of inspecting ChatGPT UI state.",
      "rationale": "Structured events are more reliable, auditable, privacy-preserving, and useful to other agents."
    }
  ],
  "tasks": [
    {
      "title": "Implement Workstreams-native session handoff command",
      "priority": "high",
      "owner": "codex"
    }
  ],
  "next_actions": [
    "Codex should inspect existing schema and propose additive migrations.",
    "OpenClaw should later consume recent events using a cursor."
  ],
  "sensitivity": "internal"
}
```

Call with `record_session_handoff`.

### Codex Implementation Summary

```json
{
  "project": "workstream-e2e-v03",
  "title": "Implemented Workstreams-native event commands",
  "summary": "Added richer event fields, agent consumption cursors, digest tools, and tests.",
  "files_changed": [
    "src/workstream_mcp/schema.py",
    "src/workstream_mcp/db.py",
    "src/workstream_mcp/tools.py"
  ],
  "commands_run": [
    "pytest -q"
  ],
  "tests_run": [
    "28 passed"
  ],
  "implementation_notes": [
    {
      "title": "Events remain canonical",
      "summary": "Existing events table was extended instead of replacing it."
    }
  ],
  "followups": [
    {
      "title": "Validate OpenClaw startup digest in the target environment",
      "owner": "any-openclaw",
      "priority": "medium"
    }
  ],
  "sensitivity": "internal"
}
```

Call with `record_codex_session_summary`.

### OpenClaw Startup

```json
{
  "agent": "albert-openclaw",
  "project": "workstream-e2e-v03",
  "include_tasks": true,
  "include_blockers": true,
  "include_recent_decisions": true,
  "include_unconsumed_events": true,
  "limit": 20
}
```

Call with `get_agent_digest`. After acting, mark handled events:

```json
{
  "event_ids": [101, 102, 103],
  "consumer_agent": "albert-openclaw",
  "action_taken": "Created inbox follow-up and updated GTD task list."
}
```

Call with `mark_event_consumed_by_agent`.

### Claude Before Helping

1. Read `get_project_brief`.
2. Call `list_recent_changes_since` with the project and any known checkpoint.
3. Avoid restating old context unless the new work changes project state.
4. Record durable decisions or handoffs before ending the session.

