from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .db import WorkstreamDB, today_utc


def _db(db_path: str | Path | None = None) -> WorkstreamDB:
    database = WorkstreamDB(db_path)
    database.initialize()
    return database


def _empty(message: str) -> str:
    return f"_{message}_"


def _line_items(rows: list[dict[str, Any]], empty_message: str, field: str = "title") -> str:
    if not rows:
        return _empty(empty_message)
    return "\n".join(f"- {row.get(field) or row.get('title')} ({row.get('created_at', '')})" for row in rows)


def render_projects(db_path: str | Path | None = None) -> str:
    projects = _db(db_path).list_projects()
    lines = ["# Workstream Projects", ""]
    if not projects:
        lines.append("_No projects recorded yet._")
    for project in projects:
        lines.append(
            f"- **{project['name']}** (`{project['slug']}`): "
            f"{project['open_tasks']} open tasks, {project['open_blockers']} open blockers"
        )
    return "\n".join(lines).strip() + "\n"


def render_recent(db_path: str | Path | None = None, limit: int = 20) -> str:
    events = _db(db_path).recent_events(limit=limit)
    lines = ["# Recent Workstream Events", ""]
    if not events:
        lines.append("_No recent events._")
    for event in events:
        lines.append(f"## {event['title']}")
        lines.append(f"- Project: `{event['project_slug']}`")
        lines.append(f"- Type: {event['event_type']}")
        lines.append(f"- Created: {event['created_at']}")
        if event.get("summary"):
            lines.append("")
            lines.append(str(event["summary"]))
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def render_today(db_path: str | Path | None = None) -> str:
    day = today_utc()
    events = _db(db_path).events_for_day(day)
    lines = [f"# Workstream Today ({day} UTC)", ""]
    if not events:
        lines.append("_No events captured today._")
    for event in events:
        lines.append(f"- **{event['title']}** (`{event['project_slug']}`, {event['event_type']})")
    return "\n".join(lines).strip() + "\n"


def render_open_tasks(db_path: str | Path | None = None) -> str:
    tasks = _db(db_path).list_open_tasks()
    lines = ["# Open Workstream Tasks", ""]
    if not tasks:
        lines.append("_No open tasks._")
    for task in tasks:
        details = [f"`{task['project_slug']}`"]
        if task.get("priority"):
            details.append(f"priority: {task['priority']}")
        if task.get("due_date"):
            details.append(f"due: {task['due_date']}")
        if task.get("owner"):
            details.append(f"owner: {task['owner']}")
        lines.append(f"- **{task['title']}** ({', '.join(details)})")
        if task.get("description"):
            lines.append(f"  {task['description']}")
    return "\n".join(lines).strip() + "\n"


def render_project(project_id: str, db_path: str | Path | None = None) -> str:
    state = _db(db_path).project_state(project_id)
    if state is None:
        return f"# Project Not Found\n\nNo project matched `{project_id}`.\n"
    project = state["project"]
    lines = [f"# {project['name']}", "", f"- Slug: `{project['slug']}`", f"- Created: {project['created_at']}", ""]
    lines.extend(["## Open Tasks", _line_items(state["open_tasks"], "No open tasks."), ""])
    lines.extend(["## Open Blockers", _line_items(state["open_blockers"], "No open blockers."), ""])
    lines.extend(["## Recent Decisions", _line_items(state["decisions"], "No decisions recorded."), ""])
    lines.extend(["## Recent Events", _line_items(state["recent_events"], "No events recorded."), ""])
    if state["codex_sessions"]:
        lines.extend(["## Codex Sessions"])
        for session in state["codex_sessions"]:
            changed_files = json.loads(session.get("changed_files_json") or "[]")
            lines.append(f"- **{session['goal']}** ({session['status']}, {session['created_at']})")
            if changed_files:
                lines.append(f"  Changed files: {', '.join(changed_files)}")
    return "\n".join(lines).strip() + "\n"


def render_project_decisions(project_id: str, db_path: str | Path | None = None) -> str:
    state = _db(db_path).project_state(project_id)
    if state is None:
        return f"# Project Not Found\n\nNo project matched `{project_id}`.\n"
    lines = [f"# Decisions for {state['project']['name']}", ""]
    if not state["decisions"]:
        lines.append("_No decisions recorded._")
    for decision in state["decisions"]:
        lines.append(f"## {decision['title']}")
        if decision.get("summary"):
            lines.append(str(decision["summary"]))
        if decision.get("rationale"):
            lines.append("")
            lines.append(f"Rationale: {decision['rationale']}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def render_project_tasks(project_id: str, db_path: str | Path | None = None) -> str:
    state = _db(db_path).project_state(project_id)
    if state is None:
        return f"# Project Not Found\n\nNo project matched `{project_id}`.\n"
    lines = [f"# Tasks for {state['project']['name']}", "", _line_items(state["open_tasks"], "No open tasks.")]
    return "\n".join(lines).strip() + "\n"


def render_project_blockers(project_id: str, db_path: str | Path | None = None) -> str:
    state = _db(db_path).project_state(project_id)
    if state is None:
        return f"# Project Not Found\n\nNo project matched `{project_id}`.\n"
    lines = [f"# Blockers for {state['project']['name']}", "", _line_items(state["open_blockers"], "No open blockers.")]
    return "\n".join(lines).strip() + "\n"
