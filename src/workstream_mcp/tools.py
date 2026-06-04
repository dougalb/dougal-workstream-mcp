from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .auth import WRITE_SCOPE, require_scope
from .db import WorkstreamDB, normalize_text
from .safety import assert_safe_to_store


def _db(db_path: str | Path | None = None) -> WorkstreamDB:
    database = WorkstreamDB(db_path)
    database.initialize()
    return database


def _as_list(value: list[Any] | None) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_int_list(value: list[int] | int | None) -> list[int]:
    if value is None:
        return []
    if isinstance(value, list):
        return [int(item) for item in value]
    return [int(value)]


def _item_title(item: Any, fallback: str) -> str:
    if isinstance(item, dict):
        return str(item.get("title") or item.get("summary") or item.get("description") or fallback)
    return str(item)


def _item_summary(item: Any) -> str | None:
    if isinstance(item, dict):
        value = item.get("summary") or item.get("description") or item.get("body") or item.get("details")
        return str(value) if value is not None else None
    return str(item) if item is not None else None


def _item_description(item: Any) -> str | None:
    if isinstance(item, dict):
        return item.get("description") or item.get("summary")
    return None


def _item_rationale(item: Any) -> str | None:
    if isinstance(item, dict):
        value = item.get("rationale")
        return str(value) if value is not None else None
    return None


def _item_owner(item: Any, fallback: str | None = None) -> str | None:
    if isinstance(item, dict):
        value = item.get("owner") or item.get("assigned_agent") or item.get("assignee")
        return str(value) if value is not None else fallback
    return fallback


def _item_priority(item: Any) -> str | None:
    if isinstance(item, dict):
        value = item.get("priority")
        return str(value) if value is not None else None
    return None


def _item_due_date(item: Any) -> str | None:
    if isinstance(item, dict):
        value = item.get("due_date") or item.get("due")
        return str(value) if value is not None else None
    return None


def _reference_parts(item: Any) -> tuple[str, str | None, str | None]:
    if isinstance(item, dict):
        uri = str(item.get("uri") or item.get("url") or item.get("href") or item.get("reference") or "")
        label = item.get("label") or item.get("title")
        description = item.get("description") or item.get("summary")
        return uri, label, description
    return str(item), None, None


def _create_decision_event(
    database: WorkstreamDB,
    project_id: int,
    item: Any,
    sensitivity: str,
    source: str | None = None,
    source_agent: str | None = None,
    parent_event_id: int | None = None,
    duplicate_warnings: list[str] | None = None,
) -> tuple[int | None, int | None]:
    title = _item_title(item, "Decision")
    summary = _item_summary(item)
    rationale = _item_rationale(item)
    existing = database.find_similar_decision(project_id, title, summary)
    if existing is not None and duplicate_warnings is not None:
        duplicate_warnings.append(f"Similar decision already exists: {existing['id']} ({existing['title']})")
    if existing is not None and existing.get("event_id") and parent_event_id is not None:
        database.create_event_link(project_id, parent_event_id, "decision", int(existing["id"]), "similar_existing")
        return None, int(existing["id"])

    metadata = {}
    if isinstance(item, dict):
        metadata = {
            key: value
            for key, value in {
                "alternatives_considered": item.get("alternatives_considered"),
                "implications": item.get("implications"),
            }.items()
            if value is not None
        }
    event_id = database.create_event(
        project_id=project_id,
        event_type="decision",
        source=source,
        source_agent=source_agent,
        title=title,
        summary=summary,
        rationale=rationale,
        sensitivity=sensitivity,
        metadata=metadata,
    )
    decision_id = database.create_decision(
        project_id=project_id,
        event_id=event_id,
        title=title,
        summary=summary,
        rationale=rationale,
        sensitivity=sensitivity,
    )
    database.update_event_related(event_id, related_decision_id=decision_id, metadata={**metadata, "decision_id": decision_id})
    if parent_event_id is not None:
        database.create_event_link(project_id, parent_event_id, "event", event_id, "child")
        database.create_event_link(project_id, parent_event_id, "decision", decision_id, "created")
    return event_id, decision_id


def _create_task_event(
    database: WorkstreamDB,
    project_id: int,
    item: Any,
    sensitivity: str,
    source: str | None = None,
    source_agent: str | None = None,
    owner: str | None = None,
    parent_event_id: int | None = None,
    duplicate_warnings: list[str] | None = None,
) -> tuple[int | None, int | None]:
    title = _item_title(item, "Task")
    existing = database.find_similar_open_task(project_id, title)
    if existing is not None:
        if duplicate_warnings is not None:
            duplicate_warnings.append(f"Similar open task already exists: {existing['id']} ({existing['title']})")
        if parent_event_id is not None:
            database.create_event_link(project_id, parent_event_id, "task", int(existing["id"]), "similar_existing")
        return None, int(existing["id"])

    description = _item_description(item)
    task_owner = _item_owner(item, fallback=owner)
    event_id = database.create_event(
        project_id=project_id,
        event_type="task",
        source=source,
        source_agent=source_agent,
        title=title,
        summary=description,
        sensitivity=sensitivity,
        metadata={
            key: value
            for key, value in {
                "priority": _item_priority(item),
                "due_date": _item_due_date(item),
                "owner": task_owner,
            }.items()
            if value is not None
        },
    )
    task_id = database.create_task(
        project_id=project_id,
        event_id=event_id,
        title=title,
        description=description,
        priority=_item_priority(item),
        due_date=_item_due_date(item),
        owner=task_owner,
        sensitivity=sensitivity,
    )
    database.update_event_related(event_id, related_task_id=task_id, metadata={"task_id": task_id})
    if parent_event_id is not None:
        database.create_event_link(project_id, parent_event_id, "event", event_id, "child")
        database.create_event_link(project_id, parent_event_id, "task", task_id, "created")
    return event_id, task_id


def _create_blocker_event(
    database: WorkstreamDB,
    project_id: int,
    item: Any,
    sensitivity: str,
    source: str | None = None,
    source_agent: str | None = None,
    parent_event_id: int | None = None,
) -> tuple[int, int]:
    title = _item_title(item, "Blocker")
    description = _item_description(item)
    event_id = database.create_event(
        project_id=project_id,
        event_type="blocker",
        source=source,
        source_agent=source_agent,
        title=title,
        summary=description,
        sensitivity=sensitivity,
        metadata={"owner": _item_owner(item)} if _item_owner(item) else {},
    )
    blocker_id = database.create_blocker(
        project_id=project_id,
        event_id=event_id,
        title=title,
        description=description,
        owner=_item_owner(item),
        sensitivity=sensitivity,
    )
    database.update_event_related(event_id, related_blocker_id=blocker_id, metadata={"blocker_id": blocker_id})
    if parent_event_id is not None:
        database.create_event_link(project_id, parent_event_id, "event", event_id, "child")
        database.create_event_link(project_id, parent_event_id, "blocker", blocker_id, "created")
    return event_id, blocker_id


def _create_reference_event(
    database: WorkstreamDB,
    project_id: int,
    item: Any,
    sensitivity: str,
    source: str | None = None,
    source_agent: str | None = None,
    parent_event_id: int | None = None,
) -> tuple[int | None, int | None]:
    uri, label, description = _reference_parts(item)
    if not uri:
        return None, None
    event_id = database.create_event(
        project_id=project_id,
        event_type="reference",
        source=source,
        source_agent=source_agent,
        title=label or uri,
        summary=description,
        references=[{"label": label, "uri": uri, "description": description}],
        sensitivity=sensitivity,
    )
    reference_id = database.create_reference(
        project_id=project_id,
        event_id=event_id,
        uri=uri,
        label=label,
        description=description,
        sensitivity=sensitivity,
    )
    if parent_event_id is not None:
        database.create_event_link(project_id, parent_event_id, "event", event_id, "child")
        database.create_event_link(project_id, parent_event_id, "reference", reference_id, "created")
    return event_id, reference_id


def _compact_summary(title: str, event_count: int, warnings: list[str]) -> str:
    suffix = f" {len(warnings)} duplication warning(s)." if warnings else ""
    return f"{title}: recorded {event_count} event(s).{suffix}"


def _event_payload(row: dict[str, Any]) -> dict[str, Any]:
    def parse_list(field: str) -> list[Any]:
        try:
            value = row.get(field) or "[]"
            parsed = json.loads(value)
        except Exception:
            return []
        return parsed if isinstance(parsed, list) else []

    def parse_dict(field: str) -> dict[str, Any]:
        try:
            value = row.get(field) or "{}"
            parsed = json.loads(value)
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "project_slug": row.get("project_slug"),
        "project_name": row.get("project_name"),
        "event_type": row["event_type"],
        "source": row.get("source"),
        "source_agent": row.get("source_agent"),
        "title": row["title"],
        "summary": row.get("summary"),
        "body": row.get("body"),
        "rationale": row.get("rationale"),
        "next_actions": parse_list("next_actions_json"),
        "references": parse_list("references_json"),
        "sensitivity": row.get("sensitivity"),
        "supersedes_event_id": row.get("supersedes_event_id"),
        "related_task_id": row.get("related_task_id"),
        "related_decision_id": row.get("related_decision_id"),
        "related_blocker_id": row.get("related_blocker_id"),
        "metadata": parse_dict("metadata_json"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


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
    require_scope(WRITE_SCOPE)
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


def record_session_handoff(
    project: str,
    source: str,
    title: str,
    summary: str,
    decisions: list[Any] | None = None,
    tasks: list[Any] | None = None,
    blockers: list[Any] | None = None,
    references: list[Any] | None = None,
    next_actions: list[Any] | None = None,
    open_questions: list[Any] | None = None,
    sensitivity: str = "internal",
    source_agent: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    require_scope(WRITE_SCOPE)
    payload = {
        "project": project,
        "source": source,
        "source_agent": source_agent,
        "title": title,
        "summary": summary,
        "decisions": decisions,
        "tasks": tasks,
        "blockers": blockers,
        "references": references,
        "next_actions": next_actions,
        "open_questions": open_questions,
        "sensitivity": sensitivity,
    }
    assert_safe_to_store(payload)
    database = _db(db_path)
    project_row = database.upsert_project(project)
    project_id = int(project_row["id"])
    warnings: list[str] = []
    event_id = database.create_event(
        project_id=project_id,
        event_type="handoff",
        source=source,
        source_agent=source_agent,
        title=title,
        summary=summary,
        next_actions=_as_list(next_actions),
        references=_as_list(references),
        sensitivity=sensitivity,
        metadata={
            "command": "record_session_handoff",
            "open_questions": _as_list(open_questions),
            "decision_count": len(_as_list(decisions)),
            "task_count": len(_as_list(tasks) or _as_list(next_actions)),
            "blocker_count": len(_as_list(blockers)),
            "reference_count": len(_as_list(references)),
        },
    )

    child_event_ids: list[int] = []
    decision_ids: list[int] = []
    linked_existing_decision_ids: list[int] = []
    for item in _as_list(decisions):
        child_event_id, decision_id = _create_decision_event(
            database,
            project_id,
            item,
            sensitivity,
            source=source,
            source_agent=source_agent,
            parent_event_id=event_id,
            duplicate_warnings=warnings,
        )
        if child_event_id is not None:
            child_event_ids.append(child_event_id)
        if decision_id is not None:
            if child_event_id is None:
                linked_existing_decision_ids.append(decision_id)
            else:
                decision_ids.append(decision_id)

    task_ids: list[int] = []
    linked_existing_task_ids: list[int] = []
    task_inputs = _as_list(tasks) or _as_list(next_actions)
    for item in task_inputs:
        child_event_id, task_id = _create_task_event(
            database,
            project_id,
            item,
            sensitivity,
            source=source,
            source_agent=source_agent,
            parent_event_id=event_id,
            duplicate_warnings=warnings,
        )
        if child_event_id is not None:
            child_event_ids.append(child_event_id)
        if task_id is not None:
            if child_event_id is None:
                linked_existing_task_ids.append(task_id)
            else:
                task_ids.append(task_id)

    blocker_ids: list[int] = []
    for item in _as_list(blockers):
        child_event_id, blocker_id = _create_blocker_event(
            database,
            project_id,
            item,
            sensitivity,
            source=source,
            source_agent=source_agent,
            parent_event_id=event_id,
        )
        child_event_ids.append(child_event_id)
        blocker_ids.append(blocker_id)

    reference_ids: list[int] = []
    for item in _as_list(references):
        child_event_id, reference_id = _create_reference_event(
            database,
            project_id,
            item,
            sensitivity,
            source=source,
            source_agent=source_agent,
            parent_event_id=event_id,
        )
        if child_event_id is not None:
            child_event_ids.append(child_event_id)
        if reference_id is not None:
            reference_ids.append(reference_id)

    created_event_ids = [event_id, *child_event_ids]
    return {
        "project_id": project_id,
        "project_slug": project_row["slug"],
        "event_id": event_id,
        "handoff_event_id": event_id,
        "created_event_ids": created_event_ids,
        "decision_ids": decision_ids,
        "task_ids": task_ids,
        "blocker_ids": blocker_ids,
        "reference_ids": reference_ids,
        "linked_existing_decision_ids": linked_existing_decision_ids,
        "linked_existing_task_ids": linked_existing_task_ids,
        "duplicate_warnings": warnings,
        "summary": _compact_summary("Session handoff", len(created_event_ids), warnings),
    }


def record_decision(
    project: str,
    title: str,
    summary: str,
    rationale: str,
    sensitivity: str = "internal",
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    require_scope(WRITE_SCOPE)
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


def record_chatgpt_decision(
    project: str,
    title: str,
    summary: str,
    rationale: str,
    alternatives_considered: list[Any] | None = None,
    implications: list[Any] | None = None,
    sensitivity: str = "internal",
    supersedes_event_id: int | None = None,
    source_agent: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    require_scope(WRITE_SCOPE)
    payload = {
        "project": project,
        "title": title,
        "summary": summary,
        "rationale": rationale,
        "alternatives_considered": alternatives_considered,
        "implications": implications,
        "sensitivity": sensitivity,
        "supersedes_event_id": supersedes_event_id,
        "source_agent": source_agent,
    }
    assert_safe_to_store(payload)
    database = _db(db_path)
    project_row = database.upsert_project(project)
    project_id = int(project_row["id"])
    similar = database.find_similar_decision(project_id, title, summary)
    warnings: list[str] = []
    if similar is not None:
        warnings.append(f"Similar decision already exists: {similar['id']} ({similar['title']})")
        if normalize_text(similar.get("title")) == normalize_text(title) and normalize_text(similar.get("summary")) == normalize_text(summary):
            return {
                "project_id": project_id,
                "project_slug": project_row["slug"],
                "event_id": similar.get("event_id"),
                "decision_id": similar["id"],
                "created": False,
                "duplicate_warnings": warnings,
                "summary": "Decision already existed; no duplicate was created.",
            }

    metadata = {
        "command": "record_chatgpt_decision",
        "alternatives_considered": _as_list(alternatives_considered),
        "implications": _as_list(implications),
    }
    event_id = database.create_event(
        project_id=project_id,
        event_type="decision",
        source="chatgpt",
        source_agent=source_agent,
        title=title,
        summary=summary,
        rationale=rationale,
        supersedes_event_id=supersedes_event_id,
        sensitivity=sensitivity,
        metadata=metadata,
    )
    decision_id = database.create_decision(
        project_id=project_id,
        event_id=event_id,
        title=title,
        summary=summary,
        rationale=rationale,
        sensitivity=sensitivity,
    )
    database.update_event_related(event_id, related_decision_id=decision_id, metadata={**metadata, "decision_id": decision_id})
    return {
        "project_id": project_id,
        "project_slug": project_row["slug"],
        "event_id": event_id,
        "decision_id": decision_id,
        "created": True,
        "duplicate_warnings": warnings,
        "summary": _compact_summary("ChatGPT decision", 1, warnings),
    }


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
    require_scope(WRITE_SCOPE)
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


def record_openclaw_followup(
    project: str,
    title: str,
    description: str,
    priority: str,
    due_date: str | None = None,
    assigned_agent: str | None = "any-openclaw",
    context: str = "",
    references: list[Any] | None = None,
    sensitivity: str = "internal",
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    require_scope(WRITE_SCOPE)
    payload = {
        "project": project,
        "title": title,
        "description": description,
        "priority": priority,
        "due_date": due_date,
        "assigned_agent": assigned_agent,
        "context": context,
        "references": references,
        "sensitivity": sensitivity,
    }
    assert_safe_to_store(payload)
    database = _db(db_path)
    project_row = database.upsert_project(project)
    project_id = int(project_row["id"])
    warnings: list[str] = []
    item = {
        "title": title,
        "description": description,
        "priority": priority,
        "due_date": due_date,
        "owner": assigned_agent or "any-openclaw",
    }
    event_id, task_id = _create_task_event(
        database,
        project_id,
        item,
        sensitivity,
        source="workstream",
        source_agent=assigned_agent,
        owner=assigned_agent or "any-openclaw",
        duplicate_warnings=warnings,
    )
    reference_ids = []
    if event_id is not None:
        database.update_event_related(
            event_id,
            related_task_id=task_id,
            metadata={
                "command": "record_openclaw_followup",
                "task_id": task_id,
                "assigned_agent": assigned_agent or "any-openclaw",
                "context": context,
            },
        )
        for item_ref in _as_list(references):
            _, reference_id = _create_reference_event(
                database,
                project_id,
                item_ref,
                sensitivity,
                source="workstream",
                source_agent=assigned_agent,
                parent_event_id=event_id,
            )
            if reference_id is not None:
                reference_ids.append(reference_id)

    return {
        "project_id": project_id,
        "project_slug": project_row["slug"],
        "event_id": event_id,
        "task_id": task_id,
        "reference_ids": reference_ids,
        "assigned_agent": assigned_agent or "any-openclaw",
        "duplicate_warnings": warnings,
        "created": event_id is not None,
        "summary": "OpenClaw follow-up recorded." if event_id is not None else "Existing similar OpenClaw follow-up was linked.",
    }


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
    require_scope(WRITE_SCOPE)
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


def record_codex_session_summary(
    project: str,
    title: str,
    summary: str,
    files_changed: list[Any] | None = None,
    commands_run: list[Any] | None = None,
    tests_run: list[Any] | None = None,
    implementation_notes: list[Any] | None = None,
    decisions: list[Any] | None = None,
    tasks_created: list[Any] | None = None,
    blockers: list[Any] | None = None,
    followups: list[Any] | None = None,
    references: list[Any] | None = None,
    sensitivity: str = "internal",
    source_agent: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    require_scope(WRITE_SCOPE)
    payload = {
        "project": project,
        "title": title,
        "summary": summary,
        "files_changed": files_changed,
        "commands_run": commands_run,
        "tests_run": tests_run,
        "implementation_notes": implementation_notes,
        "decisions": decisions,
        "tasks_created": tasks_created,
        "blockers": blockers,
        "followups": followups,
        "references": references,
        "sensitivity": sensitivity,
        "source_agent": source_agent,
    }
    assert_safe_to_store(payload)
    database = _db(db_path)
    project_row = database.upsert_project(project)
    project_id = int(project_row["id"])
    warnings: list[str] = []
    tests_summary = "\n".join(_item_title(item, "Test run") for item in _as_list(tests_run))
    metadata = {
        "command": "record_codex_session_summary",
        "files_changed": _as_list(files_changed),
        "commands_run": _as_list(commands_run),
        "tests_run": _as_list(tests_run),
    }
    event_id = database.create_event(
        project_id=project_id,
        event_type="session_summary",
        source="codex",
        source_agent=source_agent,
        title=title,
        summary=summary,
        body="\n".join(_item_title(item, "Implementation note") for item in _as_list(implementation_notes)) or None,
        references=_as_list(references),
        sensitivity=sensitivity,
        metadata=metadata,
    )
    session_id = database.create_codex_session(
        project_id=project_id,
        event_id=event_id,
        repo_path=None,
        host=None,
        goal=title,
        status="recorded",
        changed_files=[str(item) for item in _as_list(files_changed)],
        commands_run=[str(item) for item in _as_list(commands_run)],
        tests_summary=tests_summary or summary,
        sensitivity=sensitivity,
    )
    database.update_event_related(event_id, metadata={**metadata, "codex_session_id": session_id})

    child_event_ids: list[int] = []
    implementation_note_event_ids: list[int] = []
    for item in _as_list(implementation_notes):
        note_event_id = database.create_event(
            project_id=project_id,
            event_type="implementation_note",
            source="codex",
            source_agent=source_agent,
            title=_item_title(item, "Implementation note"),
            summary=_item_summary(item),
            sensitivity=sensitivity,
            metadata={"session_event_id": event_id, "codex_session_id": session_id},
        )
        database.create_event_link(project_id, event_id, "event", note_event_id, "child")
        child_event_ids.append(note_event_id)
        implementation_note_event_ids.append(note_event_id)

    decision_ids: list[int] = []
    for item in _as_list(decisions):
        child_event_id, decision_id = _create_decision_event(
            database,
            project_id,
            item,
            sensitivity,
            source="codex",
            source_agent=source_agent,
            parent_event_id=event_id,
            duplicate_warnings=warnings,
        )
        if child_event_id is not None:
            child_event_ids.append(child_event_id)
        if decision_id is not None:
            decision_ids.append(decision_id)

    task_ids: list[int] = []
    linked_existing_task_ids: list[int] = []
    for item in [*_as_list(tasks_created), *_as_list(followups)]:
        child_event_id, task_id = _create_task_event(
            database,
            project_id,
            item,
            sensitivity,
            source="codex",
            source_agent=source_agent,
            parent_event_id=event_id,
            duplicate_warnings=warnings,
        )
        if child_event_id is not None:
            child_event_ids.append(child_event_id)
        if task_id is not None:
            if child_event_id is None:
                linked_existing_task_ids.append(task_id)
            else:
                task_ids.append(task_id)

    blocker_ids: list[int] = []
    for item in _as_list(blockers):
        child_event_id, blocker_id = _create_blocker_event(
            database,
            project_id,
            item,
            sensitivity,
            source="codex",
            source_agent=source_agent,
            parent_event_id=event_id,
        )
        child_event_ids.append(child_event_id)
        blocker_ids.append(blocker_id)

    reference_ids: list[int] = []
    for item in _as_list(references):
        child_event_id, reference_id = _create_reference_event(
            database,
            project_id,
            item,
            sensitivity,
            source="codex",
            source_agent=source_agent,
            parent_event_id=event_id,
        )
        if child_event_id is not None:
            child_event_ids.append(child_event_id)
        if reference_id is not None:
            reference_ids.append(reference_id)

    created_event_ids = [event_id, *child_event_ids]
    return {
        "project_id": project_id,
        "project_slug": project_row["slug"],
        "event_id": event_id,
        "session_event_id": event_id,
        "codex_session_id": session_id,
        "created_event_ids": created_event_ids,
        "implementation_note_event_ids": implementation_note_event_ids,
        "decision_ids": decision_ids,
        "task_ids": task_ids,
        "linked_existing_task_ids": linked_existing_task_ids,
        "blocker_ids": blocker_ids,
        "reference_ids": reference_ids,
        "duplicate_warnings": warnings,
        "summary": _compact_summary("Codex session summary", len(created_event_ids), warnings),
    }


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
) -> dict[str, Any]:
    payload = {
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
    assert_safe_to_store(payload)
    database = _db(db_path)
    rows = database.list_recent_changes_since(
        project=project,
        since_event_id=since_event_id,
        since_timestamp=since_timestamp,
        source_filter=source_filter,
        event_type_filter=event_type_filter,
        include_consumed=include_consumed,
        consumer_agent=consumer_agent,
        limit=limit,
        order=order,
    )
    events = [_event_payload(row) for row in rows]
    return {
        "events": events,
        "count": len(events),
        "consumer_agent": consumer_agent,
        "include_consumed": include_consumed,
    }


def mark_event_consumed_by_agent(
    consumer_agent: str,
    event_ids: list[int] | None = None,
    event_id: int | None = None,
    project: str | None = None,
    notes: str | None = None,
    action_taken: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    require_scope(WRITE_SCOPE)
    payload = {
        "consumer_agent": consumer_agent,
        "event_ids": event_ids,
        "event_id": event_id,
        "project": project,
        "notes": notes,
        "action_taken": action_taken,
    }
    assert_safe_to_store(payload)
    ids = [*_as_int_list(event_ids), *_as_int_list(event_id)]
    database = _db(db_path)
    result = database.mark_events_consumed(
        event_ids=ids,
        consumer_agent=consumer_agent,
        notes=notes,
        action_taken=action_taken,
        project=project,
    )
    return {
        **result,
        "consumer_agent": consumer_agent,
        "summary": f"Marked {len(result['consumed_event_ids'])} event(s) consumed by {consumer_agent}.",
    }


def get_agent_digest(
    agent: str,
    project: str | None = None,
    include_tasks: bool = True,
    include_blockers: bool = True,
    include_recent_decisions: bool = True,
    include_unconsumed_events: bool = True,
    limit: int = 20,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    payload = {
        "agent": agent,
        "project": project,
        "include_tasks": include_tasks,
        "include_blockers": include_blockers,
        "include_recent_decisions": include_recent_decisions,
        "include_unconsumed_events": include_unconsumed_events,
        "limit": limit,
    }
    assert_safe_to_store(payload)
    database = _db(db_path)
    unconsumed_events = []
    if include_unconsumed_events:
        unconsumed_events = [
            _event_payload(row)
            for row in database.list_recent_changes_since(
                project=project,
                consumer_agent=agent,
                include_consumed=False,
                limit=limit,
                order="asc",
            )
        ]
    assigned_tasks = database.assigned_tasks_for_agent(agent=agent, project=project, limit=limit) if include_tasks else []
    open_blockers = database.open_blockers(project=project, limit=limit) if include_blockers else []
    recent_decisions = database.recent_decisions(project=project, limit=limit) if include_recent_decisions else []
    stale_items = database.stale_tasks_for_agent(agent=agent, project=project, limit=limit) if include_tasks else []
    return {
        "agent": agent,
        "project": project,
        "unconsumed_events": unconsumed_events,
        "assigned_open_tasks": assigned_tasks,
        "open_blockers": open_blockers,
        "recent_decisions": recent_decisions,
        "requested_followups": [
            task for task in assigned_tasks if task.get("owner") in {agent, "any-openclaw", "any-codex"}
        ],
        "stale_items": stale_items,
        "summary": (
            f"{agent}: {len(unconsumed_events)} unconsumed event(s), "
            f"{len(assigned_tasks)} assigned open task(s), {len(open_blockers)} open blocker(s)."
        ),
    }


def create_or_update_project_brief(
    project: str,
    summary_delta: str,
    status: str | None = None,
    current_state: str | None = None,
    next_steps: list[Any] | None = None,
    risks: list[Any] | None = None,
    source_event_ids: list[int] | None = None,
    sensitivity: str = "internal",
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    require_scope(WRITE_SCOPE)
    payload = {
        "project": project,
        "summary_delta": summary_delta,
        "status": status,
        "current_state": current_state,
        "next_steps": next_steps,
        "risks": risks,
        "source_event_ids": source_event_ids,
        "sensitivity": sensitivity,
    }
    assert_safe_to_store(payload)
    database = _db(db_path)
    project_row = database.upsert_project(project)
    project_id = int(project_row["id"])
    event_id = database.create_event(
        project_id=project_id,
        event_type="project_brief",
        source="workstream",
        title=f"Project brief updated: {project_row['name']}",
        summary=summary_delta,
        body=current_state,
        next_actions=_as_list(next_steps),
        sensitivity=sensitivity,
        metadata={
            "command": "create_or_update_project_brief",
            "status": status,
            "risks": _as_list(risks),
            "source_event_ids": _as_list(source_event_ids),
        },
    )
    for source_event_id in _as_int_list(source_event_ids):
        database.create_event_link(project_id, event_id, "event", source_event_id, "source")
    brief = database.upsert_project_brief(
        project_id=project_id,
        summary_delta=summary_delta,
        status=status,
        current_state=current_state,
        next_steps=_as_list(next_steps) if next_steps is not None else None,
        risks=_as_list(risks) if risks is not None else None,
        source_event_ids=_as_int_list(source_event_ids),
        sensitivity=sensitivity,
    )
    return {
        "project_id": project_id,
        "project_slug": project_row["slug"],
        "event_id": event_id,
        "brief_id": brief["id"],
        "brief": {
            "summary": brief["summary"],
            "status": brief.get("status"),
            "current_state": brief.get("current_state"),
            "next_steps": json.loads(brief.get("next_steps_json") or "[]"),
            "risks": json.loads(brief.get("risks_json") or "[]"),
            "source_event_ids": json.loads(brief.get("source_event_ids_json") or "[]"),
            "sensitivity": brief.get("sensitivity"),
            "updated_at": brief.get("updated_at"),
        },
        "summary": "Project brief updated from structured workstream state.",
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
    require_scope(WRITE_SCOPE)
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
    require_scope(WRITE_SCOPE)
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
