from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from mcp.types import CallToolResult, TextContent

from .auth import SENSITIVE_SCOPE, current_scopes
from .db import WorkstreamDB
from .safety import SecretDetectedError, assert_safe_to_store

SENSITIVE_VALUES = {"restricted", "sensitive", "secret", "confidential", "private"}
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
        "recent_events": [
            _safe_row(row, ["id", "event_type", "source", "title", "summary", "created_at"])
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
