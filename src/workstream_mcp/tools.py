from __future__ import annotations

from pathlib import Path
from typing import Any

from .db import WorkstreamDB
from .safety import assert_safe_to_store


def _db(db_path: str | Path | None = None) -> WorkstreamDB:
    database = WorkstreamDB(db_path)
    database.initialize()
    return database


def _as_list(value: list[Any] | None) -> list[Any]:
    return value if isinstance(value, list) else []


def _item_title(item: Any, fallback: str) -> str:
    if isinstance(item, dict):
        return str(item.get("title") or item.get("summary") or item.get("description") or fallback)
    return str(item)


def _item_description(item: Any) -> str | None:
    if isinstance(item, dict):
        return item.get("description") or item.get("summary")
    return None


def _reference_parts(item: Any) -> tuple[str, str | None, str | None]:
    if isinstance(item, dict):
        uri = str(item.get("uri") or item.get("url") or item.get("href") or item.get("reference") or "")
        label = item.get("label") or item.get("title")
        description = item.get("description") or item.get("summary")
        return uri, label, description
    return str(item), None, None


def capture_handoff(
    source: str,
    project: str,
    title: str,
    summary: str,
    decisions: list[Any] | None = None,
    next_actions: list[Any] | None = None,
    blockers: list[Any] | None = None,
    references: list[Any] | None = None,
    sensitivity: str = "internal",
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    payload = {
        "source": source,
        "project": project,
        "title": title,
        "summary": summary,
        "decisions": decisions,
        "next_actions": next_actions,
        "blockers": blockers,
        "references": references,
        "sensitivity": sensitivity,
    }
    assert_safe_to_store(payload)
    database = _db(db_path)
    project_row = database.upsert_project(project)
    project_id = int(project_row["id"])
    event_id = database.create_event(
        project_id=project_id,
        event_type="handoff",
        source=source,
        title=title,
        summary=summary,
        sensitivity=sensitivity,
        metadata={"next_actions_count": len(_as_list(next_actions))},
    )

    decision_ids = [
        database.create_decision(
            project_id=project_id,
            event_id=event_id,
            title=_item_title(item, "Decision"),
            summary=item.get("summary") if isinstance(item, dict) else str(item),
            rationale=item.get("rationale") if isinstance(item, dict) else None,
            sensitivity=sensitivity,
        )
        for item in _as_list(decisions)
    ]
    task_ids = [
        database.create_task(
            project_id=project_id,
            event_id=event_id,
            title=_item_title(item, "Next action"),
            description=_item_description(item),
            priority=item.get("priority") if isinstance(item, dict) else None,
            due_date=item.get("due_date") if isinstance(item, dict) else None,
            owner=item.get("owner") if isinstance(item, dict) else None,
            sensitivity=sensitivity,
        )
        for item in _as_list(next_actions)
    ]
    blocker_ids = [
        database.create_blocker(
            project_id=project_id,
            event_id=event_id,
            title=_item_title(item, "Blocker"),
            description=_item_description(item),
            owner=item.get("owner") if isinstance(item, dict) else None,
            sensitivity=sensitivity,
        )
        for item in _as_list(blockers)
    ]
    reference_ids = []
    for item in _as_list(references):
        uri, label, description = _reference_parts(item)
        if uri:
            reference_ids.append(
                database.create_reference(
                    project_id=project_id,
                    event_id=event_id,
                    uri=uri,
                    label=label,
                    description=description,
                    sensitivity=sensitivity,
                )
            )

    return {
        "project_id": project_id,
        "project_slug": project_row["slug"],
        "event_id": event_id,
        "decision_ids": decision_ids,
        "task_ids": task_ids,
        "blocker_ids": blocker_ids,
        "reference_ids": reference_ids,
    }


def record_decision(
    project: str,
    title: str,
    summary: str,
    rationale: str,
    sensitivity: str = "internal",
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    payload = locals().copy()
    payload.pop("db_path", None)
    assert_safe_to_store(payload)
    database = _db(db_path)
    project_row = database.upsert_project(project)
    project_id = int(project_row["id"])
    event_id = database.create_event(
        project_id=project_id,
        event_type="decision",
        title=title,
        summary=summary,
        sensitivity=sensitivity,
    )
    decision_id = database.create_decision(
        project_id=project_id,
        event_id=event_id,
        title=title,
        summary=summary,
        rationale=rationale,
        sensitivity=sensitivity,
    )
    return {"project_id": project_id, "project_slug": project_row["slug"], "event_id": event_id, "decision_id": decision_id}


def record_task(
    project: str,
    title: str,
    description: str = "",
    priority: str | None = None,
    due_date: str | None = None,
    owner: str | None = None,
    sensitivity: str = "internal",
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    payload = locals().copy()
    payload.pop("db_path", None)
    assert_safe_to_store(payload)
    database = _db(db_path)
    project_row = database.upsert_project(project)
    project_id = int(project_row["id"])
    event_id = database.create_event(
        project_id=project_id,
        event_type="task",
        title=title,
        summary=description,
        sensitivity=sensitivity,
    )
    task_id = database.create_task(
        project_id=project_id,
        event_id=event_id,
        title=title,
        description=description,
        priority=priority,
        due_date=due_date,
        owner=owner,
        sensitivity=sensitivity,
    )
    return {"project_id": project_id, "project_slug": project_row["slug"], "event_id": event_id, "task_id": task_id}


def record_codex_session(
    project: str,
    repo_path: str,
    host: str,
    goal: str,
    status: str,
    changed_files: list[str] | None = None,
    commands_run: list[str] | None = None,
    tests_summary: str = "",
    decisions: list[Any] | None = None,
    next_actions: list[Any] | None = None,
    blockers: list[Any] | None = None,
    sensitivity: str = "internal",
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    payload = {
        "project": project,
        "repo_path": repo_path,
        "host": host,
        "goal": goal,
        "status": status,
        "changed_files": changed_files,
        "commands_run": commands_run,
        "tests_summary": tests_summary,
        "decisions": decisions,
        "next_actions": next_actions,
        "blockers": blockers,
        "sensitivity": sensitivity,
    }
    assert_safe_to_store(payload)
    database = _db(db_path)
    project_row = database.upsert_project(project)
    project_id = int(project_row["id"])
    event_id = database.create_event(
        project_id=project_id,
        event_type="codex_session",
        source="codex",
        title=f"Codex session: {goal}",
        summary=tests_summary,
        sensitivity=sensitivity,
        metadata={"status": status},
    )
    session_id = database.create_codex_session(
        project_id=project_id,
        event_id=event_id,
        repo_path=repo_path,
        host=host,
        goal=goal,
        status=status,
        changed_files=changed_files or [],
        commands_run=commands_run or [],
        tests_summary=tests_summary,
        sensitivity=sensitivity,
    )
    decision_ids = [
        database.create_decision(
            project_id=project_id,
            event_id=event_id,
            session_id=session_id,
            title=_item_title(item, "Decision"),
            summary=item.get("summary") if isinstance(item, dict) else str(item),
            rationale=item.get("rationale") if isinstance(item, dict) else None,
            sensitivity=sensitivity,
        )
        for item in _as_list(decisions)
    ]
    task_ids = [
        database.create_task(
            project_id=project_id,
            event_id=event_id,
            session_id=session_id,
            title=_item_title(item, "Next action"),
            description=_item_description(item),
            priority=item.get("priority") if isinstance(item, dict) else None,
            due_date=item.get("due_date") if isinstance(item, dict) else None,
            owner=item.get("owner") if isinstance(item, dict) else None,
            sensitivity=sensitivity,
        )
        for item in _as_list(next_actions)
    ]
    blocker_ids = [
        database.create_blocker(
            project_id=project_id,
            event_id=event_id,
            session_id=session_id,
            title=_item_title(item, "Blocker"),
            description=_item_description(item),
            owner=item.get("owner") if isinstance(item, dict) else None,
            sensitivity=sensitivity,
        )
        for item in _as_list(blockers)
    ]
    return {
        "project_id": project_id,
        "project_slug": project_row["slug"],
        "event_id": event_id,
        "codex_session_id": session_id,
        "decision_ids": decision_ids,
        "task_ids": task_ids,
        "blocker_ids": blocker_ids,
    }


def search_workstream(
    query: str,
    project: str | None = None,
    limit: int = 20,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    assert_safe_to_store({"query": query, "project": project})
    database = _db(db_path)
    return {"results": database.search(query=query, project=project, limit=limit)}


def update_task_status(
    task_id: int,
    status: str,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    assert_safe_to_store({"task_id": task_id, "status": status})
    database = _db(db_path)
    row = database.update_task_status(task_id=task_id, status=status)
    return {
        "task_id": row["id"],
        "project_id": row["project_id"],
        "project_slug": row["project_slug"],
        "status": row["status"],
        "event_id": row["event_id"],
    }


def update_blocker_status(
    blocker_id: int,
    status: str,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    assert_safe_to_store({"blocker_id": blocker_id, "status": status})
    database = _db(db_path)
    row = database.update_blocker_status(blocker_id=blocker_id, status=status)
    return {
        "blocker_id": row["id"],
        "project_id": row["project_id"],
        "project_slug": row["project_slug"],
        "status": row["status"],
        "event_id": row["event_id"],
    }
