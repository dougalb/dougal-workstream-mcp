from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from mcp.types import CallToolResult, TextContent

from .auth import SENSITIVE_SCOPE, current_scopes
from .db import WorkstreamDB
from .safety import SecretDetectedError, assert_safe_to_store

SENSITIVE_VALUES = {"restricted", "sensitive", "secret", "confidential", "private", "personal"}
LOCAL_PATH_RE = re.compile(r"(?<![\w:/.-])(?:~|/[\w ._@%+=:,/-]{2,})")


def _db(db_path: str | Path | None = None) -> WorkstreamDB:
    database = WorkstreamDB(db_path)
    database.initialize()
    return database


def _can_include_sensitive() -> bool:
    return SENSITIVE_SCOPE in current_scopes()


def _row_allowed(row: dict[str, Any], include_sensitive: bool) -> bool:
    if include_sensitive:
        return True
    return str(row.get("sensitivity", "internal")).lower() not in SENSITIVE_VALUES


def _safe_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    try:
        assert_safe_to_store({"value": text})
    except SecretDetectedError:
        return "[redacted]"
    return LOCAL_PATH_RE.sub("[local path]", text)


def _safe_row(row: dict[str, Any], fields: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for field in fields:
        if field in row and row[field] is not None:
            value = row[field]
            if isinstance(value, str):
                result[field] = _safe_text(value)
            else:
                result[field] = value
    return result


def _safe_reference(row: dict[str, Any]) -> dict[str, Any]:
    uri = str(row.get("uri") or "")
    safe = _safe_row(row, ["id", "label", "description", "created_at"])
    if uri.startswith(("1password://", "op://", "vault://")):
        safe["uri"] = "[secret reference]"
    else:
        safe["uri"] = _safe_text(uri)
    return safe


def _safe_changed_files(raw: str | None) -> list[str]:
    try:
        values = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    safe_values = []
    for value in values:
        text = _safe_text(value)
        if text:
            safe_values.append(text)
    return safe_values


def _json_list(raw: str | None) -> list[Any]:
    try:
        parsed = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _json_dict(raw: str | None) -> dict[str, Any]:
    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _safe_json_value(value: Any) -> Any:
    if isinstance(value, str):
        return _safe_text(value)
    if isinstance(value, list):
        return [_safe_json_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _safe_json_value(item) for key, item in value.items()}
    return value


def _safe_json_list(raw: str | None) -> list[Any]:
    return [_safe_json_value(item) for item in _json_list(raw)]


def _safe_event(row: dict[str, Any]) -> dict[str, Any]:
    safe = _safe_row(
        row,
        [
            "id",
            "project_id",
            "project_slug",
            "project_name",
            "event_type",
            "source",
            "source_agent",
            "title",
            "summary",
            "body",
            "rationale",
            "sensitivity",
            "supersedes_event_id",
            "related_task_id",
            "related_decision_id",
            "related_blocker_id",
            "created_at",
            "updated_at",
        ],
    )
    safe["next_actions"] = _safe_json_list(row.get("next_actions_json"))
    safe["references"] = _safe_json_list(row.get("references_json"))
    metadata = _json_dict(row.get("metadata_json"))
    safe["metadata"] = {
        key: _safe_json_value(value)
        for key, value in metadata.items()
        if key not in {"commands_run"}
    }
    return safe


def project_state(project: str, db_path: str | Path | None = None) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    state = _db(db_path).project_state(project)
    if state is None:
        return None, {"omitted_sensitive_rows": 0}

    include_sensitive = _can_include_sensitive()
    omitted = 0

    def allowed(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        nonlocal omitted
        kept = []
        for row in rows:
            if _row_allowed(row, include_sensitive):
                kept.append(row)
            else:
                omitted += 1
        return kept

    safe_state = {
        "project": _safe_row(state["project"], ["id", "slug", "name", "created_at", "updated_at"]),
        "project_brief": (
            {
                **_safe_row(
                    state["project_brief"],
                    ["id", "summary", "status", "current_state", "sensitivity", "created_at", "updated_at"],
                ),
                "next_steps": _safe_json_list(state["project_brief"].get("next_steps_json")),
                "risks": _safe_json_list(state["project_brief"].get("risks_json")),
                "source_event_ids": _json_list(state["project_brief"].get("source_event_ids_json")),
            }
            if state.get("project_brief") and _row_allowed(state["project_brief"], include_sensitive)
            else None
        ),
        "recent_events": [
            _safe_row(row, ["id", "event_type", "source", "source_agent", "title", "summary", "created_at"])
            for row in allowed(state["recent_events"])
        ],
        "open_tasks": [
            _safe_row(row, ["id", "title", "description", "status", "priority", "due_date", "owner", "created_at"])
            for row in allowed(state["open_tasks"])
        ],
        "decisions": [
            _safe_row(row, ["id", "title", "summary", "rationale", "created_at"]) for row in allowed(state["decisions"])
        ],
        "open_blockers": [
            _safe_row(row, ["id", "title", "description", "status", "owner", "created_at"])
            for row in allowed(state["open_blockers"])
        ],
        "references": [_safe_reference(row) for row in allowed(state["references"])],
        "codex_sessions": [
            {
                **_safe_row(row, ["id", "goal", "status", "tests_summary", "created_at"]),
                "changed_files": _safe_changed_files(row.get("changed_files_json")),
            }
            for row in allowed(state["codex_sessions"])
        ],
    }
    return safe_state, {"omitted_sensitive_rows": omitted}


def _result(text: str, structured: dict[str, Any], meta: dict[str, Any] | None = None) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=text)],
        structuredContent=structured,
        _meta=meta or {},
    )


def list_projects(db_path: str | Path | None = None) -> CallToolResult:
    projects = [
        _safe_row(row, ["id", "slug", "name", "open_tasks", "open_blockers", "last_event_at"])
        for row in _db(db_path).list_projects()
    ]
    lines = ["Workstream projects:"]
    lines.extend(f"- {row['name']} ({row['slug']}): {row.get('open_tasks', 0)} open tasks" for row in projects)
    if not projects:
        lines.append("- No projects recorded yet.")
    return _result("\n".join(lines), {"projects": projects}, {"count": len(projects)})


def list_open_tasks(project: str | None = None, db_path: str | Path | None = None) -> CallToolResult:
    include_sensitive = _can_include_sensitive()
    omitted = 0
    tasks = []
    for row in _db(db_path).list_open_tasks(project=project):
        if _row_allowed(row, include_sensitive):
            tasks.append(
                _safe_row(
                    row,
                    ["id", "project_slug", "project_name", "title", "description", "status", "priority", "due_date", "owner"],
                )
            )
        else:
            omitted += 1

    lines = ["Open workstream tasks:"]
    lines.extend(f"- [{row['project_slug']}] {row['title']} ({row['status']})" for row in tasks)
    if not tasks:
        lines.append("- No open tasks.")
    return _result("\n".join(lines), {"tasks": tasks}, {"count": len(tasks), "omitted_sensitive_rows": omitted})


def get_project_brief(project: str, db_path: str | Path | None = None) -> CallToolResult:
    state, meta = project_state(project, db_path=db_path)
    if state is None:
        return _result(f"No project matched {project}.", {"error": "project_not_found", "project": project})

    lines = [f"Project brief: {state['project']['name']} ({state['project']['slug']})"]
    lines.append(f"Open tasks: {len(state['open_tasks'])}")
    lines.append(f"Open blockers: {len(state['open_blockers'])}")
    if state["open_tasks"]:
        lines.append("Top tasks:")
        lines.extend(f"- {task['title']}" for task in state["open_tasks"][:5])
    if state["decisions"]:
        lines.append("Recent decisions:")
        lines.extend(f"- {decision['title']}" for decision in state["decisions"][:5])
    return _result("\n".join(lines), state, meta)


def search_workstream(query: str, project: str | None = None, limit: int = 20, db_path: str | Path | None = None) -> CallToolResult:
    include_sensitive = _can_include_sensitive()
    omitted = 0
    results = []
    for row in _db(db_path).search(query=query, project=project, limit=limit):
        if _row_allowed(row, include_sensitive):
            results.append(_safe_row(row, ["kind", "id", "project", "title", "snippet", "created_at"]))
        else:
            omitted += 1

    lines = [f"Search results for {query!r}:"]
    lines.extend(f"- [{row['project']}] {row['kind']}: {row['title']}" for row in results)
    if not results:
        lines.append("- No matching workstream entries.")
    return _result("\n".join(lines), {"results": results}, {"count": len(results), "omitted_sensitive_rows": omitted})


def list_recent_changes_since(
    project: str | None = None,
    since_event_id: int | None = None,
    since_timestamp: str | None = None,
    source_filter: str | list[str] | None = None,
    event_type_filter: str | list[str] | None = None,
    include_consumed: bool = False,
    consumer_agent: str | None = None,
    limit: int = 50,
    order: str = "asc",
    db_path: str | Path | None = None,
) -> CallToolResult:
    assert_safe_to_store(
        {
            "project": project,
            "since_event_id": since_event_id,
            "since_timestamp": since_timestamp,
            "source_filter": source_filter,
            "event_type_filter": event_type_filter,
            "include_consumed": include_consumed,
            "consumer_agent": consumer_agent,
            "limit": limit,
            "order": order,
        }
    )
    include_sensitive = _can_include_sensitive()
    omitted = 0
    events = []
    for row in _db(db_path).list_recent_changes_since(
        project=project,
        since_event_id=since_event_id,
        since_timestamp=since_timestamp,
        source_filter=source_filter,
        event_type_filter=event_type_filter,
        include_consumed=include_consumed,
        consumer_agent=consumer_agent,
        limit=limit,
        order=order,
    ):
        if _row_allowed(row, include_sensitive):
            events.append(_safe_event(row))
        else:
            omitted += 1

    lines = ["Recent workstream changes:"]
    lines.extend(f"- [{row['project_slug']}] #{row['id']} {row['event_type']}: {row['title']}" for row in events)
    if not events:
        lines.append("- No matching recent changes.")
    return _result(
        "\n".join(lines),
        {"events": events, "consumer_agent": consumer_agent, "include_consumed": include_consumed},
        {"count": len(events), "omitted_sensitive_rows": omitted},
    )


def get_agent_digest(
    agent: str,
    project: str | None = None,
    include_tasks: bool = True,
    include_blockers: bool = True,
    include_recent_decisions: bool = True,
    include_unconsumed_events: bool = True,
    limit: int = 20,
    db_path: str | Path | None = None,
) -> CallToolResult:
    assert_safe_to_store(
        {
            "agent": agent,
            "project": project,
            "include_tasks": include_tasks,
            "include_blockers": include_blockers,
            "include_recent_decisions": include_recent_decisions,
            "include_unconsumed_events": include_unconsumed_events,
            "limit": limit,
        }
    )
    database = _db(db_path)
    include_sensitive = _can_include_sensitive()
    omitted = 0

    def allowed_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        nonlocal omitted
        kept = []
        for row in rows:
            if _row_allowed(row, include_sensitive):
                kept.append(row)
            else:
                omitted += 1
        return kept

    unconsumed_events = []
    if include_unconsumed_events:
        unconsumed_events = [
            _safe_event(row)
            for row in allowed_rows(
                database.list_recent_changes_since(
                    project=project,
                    consumer_agent=agent,
                    include_consumed=False,
                    limit=limit,
                    order="asc",
                )
            )
        ]
    assigned_tasks = [
        _safe_row(row, ["id", "project_slug", "project_name", "title", "description", "status", "priority", "due_date", "owner"])
        for row in allowed_rows(database.assigned_tasks_for_agent(agent=agent, project=project, limit=limit) if include_tasks else [])
    ]
    open_blockers = [
        _safe_row(row, ["id", "project_slug", "project_name", "title", "description", "status", "owner", "created_at"])
        for row in allowed_rows(database.open_blockers(project=project, limit=limit) if include_blockers else [])
    ]
    recent_decisions = [
        _safe_row(row, ["id", "project_slug", "project_name", "title", "summary", "rationale", "created_at"])
        for row in allowed_rows(database.recent_decisions(project=project, limit=limit) if include_recent_decisions else [])
    ]
    stale_items = [
        _safe_row(row, ["id", "project_slug", "project_name", "title", "description", "status", "priority", "due_date", "owner"])
        for row in allowed_rows(database.stale_tasks_for_agent(agent=agent, project=project, limit=limit) if include_tasks else [])
    ]
    requested_followups = [
        task for task in assigned_tasks if task.get("owner") in {agent, "any-openclaw", "any-codex"}
    ]

    lines = [f"Digest for {agent}:"]
    lines.append(f"- Unconsumed events: {len(unconsumed_events)}")
    lines.append(f"- Assigned open tasks: {len(assigned_tasks)}")
    lines.append(f"- Open blockers: {len(open_blockers)}")
    if assigned_tasks:
        lines.append("Assigned tasks:")
        lines.extend(f"- [{task['project_slug']}] {task['title']}" for task in assigned_tasks[:5])
    if unconsumed_events:
        lines.append("Unconsumed events:")
        lines.extend(f"- [{event['project_slug']}] #{event['id']} {event['title']}" for event in unconsumed_events[:5])
    return _result(
        "\n".join(lines),
        {
            "agent": agent,
            "project": project,
            "unconsumed_events": unconsumed_events,
            "assigned_open_tasks": assigned_tasks,
            "open_blockers": open_blockers,
            "recent_decisions": recent_decisions,
            "requested_followups": requested_followups,
            "stale_items": stale_items,
        },
        {"omitted_sensitive_rows": omitted},
    )
