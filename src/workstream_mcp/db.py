from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import load_config
from .schema import SCHEMA_SQL

EVENT_COLUMN_MIGRATIONS = {
    "source_agent": "TEXT",
    "body": "TEXT",
    "rationale": "TEXT",
    "next_actions_json": "TEXT NOT NULL DEFAULT '[]'",
    "references_json": "TEXT NOT NULL DEFAULT '[]'",
    "supersedes_event_id": "INTEGER",
    "related_task_id": "INTEGER",
    "related_decision_id": "INTEGER",
    "related_blocker_id": "INTEGER",
}


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def today_utc() -> str:
    return datetime.now(UTC).date().isoformat()


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "project"


def normalize_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}


def json_list(value: str | None) -> list[Any]:
    try:
        parsed = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def json_dict(value: str | None) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


class WorkstreamDB:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path is not None else load_config().db_path

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA_SQL)
            self._apply_migrations(conn)

    def _apply_migrations(self, conn: sqlite3.Connection) -> None:
        event_columns = {row["name"] for row in conn.execute("PRAGMA table_info(events)").fetchall()}
        for column, definition in EVENT_COLUMN_MIGRATIONS.items():
            if column not in event_columns:
                conn.execute(f"ALTER TABLE events ADD COLUMN {column} {definition}")
        conn.commit()

    def query_all(self, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return [row_to_dict(row) or {} for row in conn.execute(sql, tuple(params)).fetchall()]

    def query_one(self, sql: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
        with self.connect() as conn:
            return row_to_dict(conn.execute(sql, tuple(params)).fetchone())

    def upsert_project(self, name: str) -> dict[str, Any]:
        self.initialize()
        now = utc_now()
        slug = slugify(name)
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM projects WHERE slug = ?", (slug,)).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO projects (slug, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
                    (slug, name.strip() or slug, now, now),
                )
            else:
                conn.execute(
                    "UPDATE projects SET name = ?, updated_at = ? WHERE slug = ?",
                    (name.strip() or slug, now, slug),
                )
            conn.commit()
        project = self.get_project(slug)
        if project is None:
            raise RuntimeError("Failed to upsert project")
        return project

    def get_project(self, project_id: int | str) -> dict[str, Any] | None:
        self.initialize()
        if isinstance(project_id, int) or str(project_id).isdigit():
            return self.query_one("SELECT * FROM projects WHERE id = ?", (int(project_id),))

        value = str(project_id).strip()
        slug = slugify(value)
        return self.query_one(
            """
            SELECT * FROM projects
            WHERE slug = ? OR lower(name) = lower(?)
            ORDER BY CASE WHEN slug = ? THEN 0 ELSE 1 END
            LIMIT 1
            """,
            (slug, value, slug),
        )

    def create_event(
        self,
        project_id: int,
        event_type: str,
        title: str,
        summary: str | None = None,
        source: str | None = None,
        source_agent: str | None = None,
        body: str | None = None,
        rationale: str | None = None,
        next_actions: list[Any] | None = None,
        references: list[Any] | None = None,
        sensitivity: str = "internal",
        supersedes_event_id: int | None = None,
        related_task_id: int | None = None,
        related_decision_id: int | None = None,
        related_blocker_id: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        now = utc_now()
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO events (
                    project_id, event_type, source, source_agent, title, summary,
                    body, rationale, next_actions_json, references_json, sensitivity,
                    supersedes_event_id, related_task_id, related_decision_id,
                    related_blocker_id,
                    metadata_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    event_type,
                    source,
                    source_agent,
                    title,
                    summary,
                    body,
                    rationale,
                    json.dumps(next_actions or [], sort_keys=True),
                    json.dumps(references or [], sort_keys=True),
                    sensitivity,
                    supersedes_event_id,
                    related_task_id,
                    related_decision_id,
                    related_blocker_id,
                    json.dumps(metadata or {}, sort_keys=True),
                    now,
                    now,
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def create_task(
        self,
        project_id: int,
        title: str,
        description: str | None = None,
        priority: str | None = None,
        due_date: str | None = None,
        owner: str | None = None,
        sensitivity: str = "internal",
        event_id: int | None = None,
        session_id: int | None = None,
        status: str = "open",
    ) -> int:
        now = utc_now()
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO tasks (
                    project_id, event_id, session_id, title, description, status,
                    priority, due_date, owner, sensitivity, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    event_id,
                    session_id,
                    title,
                    description,
                    status,
                    priority,
                    due_date,
                    owner,
                    sensitivity,
                    now,
                    now,
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def create_decision(
        self,
        project_id: int,
        title: str,
        summary: str | None = None,
        rationale: str | None = None,
        sensitivity: str = "internal",
        event_id: int | None = None,
        session_id: int | None = None,
    ) -> int:
        now = utc_now()
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO decisions (
                    project_id, event_id, session_id, title, summary, rationale,
                    sensitivity, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    event_id,
                    session_id,
                    title,
                    summary,
                    rationale,
                    sensitivity,
                    now,
                    now,
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def create_blocker(
        self,
        project_id: int,
        title: str,
        description: str | None = None,
        owner: str | None = None,
        sensitivity: str = "internal",
        event_id: int | None = None,
        session_id: int | None = None,
        status: str = "open",
    ) -> int:
        now = utc_now()
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO blockers (
                    project_id, event_id, session_id, title, description, status,
                    owner, sensitivity, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    event_id,
                    session_id,
                    title,
                    description,
                    status,
                    owner,
                    sensitivity,
                    now,
                    now,
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def create_reference(
        self,
        project_id: int,
        uri: str,
        label: str | None = None,
        description: str | None = None,
        sensitivity: str = "internal",
        event_id: int | None = None,
        session_id: int | None = None,
    ) -> int:
        now = utc_now()
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO "references" (
                    project_id, event_id, session_id, label, uri, description,
                    sensitivity, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    event_id,
                    session_id,
                    label,
                    uri,
                    description,
                    sensitivity,
                    now,
                    now,
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def create_codex_session(
        self,
        project_id: int,
        event_id: int,
        repo_path: str | None,
        host: str | None,
        goal: str,
        status: str,
        changed_files: list[str],
        commands_run: list[str],
        tests_summary: str | None,
        sensitivity: str = "internal",
    ) -> int:
        now = utc_now()
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO codex_sessions (
                    project_id, event_id, repo_path, host, goal, status,
                    changed_files_json, commands_run_json, tests_summary,
                    sensitivity, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    event_id,
                    repo_path,
                    host,
                    goal,
                    status,
                    json.dumps(changed_files),
                    json.dumps(commands_run),
                    tests_summary,
                    sensitivity,
                    now,
                    now,
                ),
            )
            session_id = int(cursor.lastrowid)
            conn.execute(
                "UPDATE events SET metadata_json = ?, updated_at = ? WHERE id = ?",
                (json.dumps({"codex_session_id": session_id}, sort_keys=True), now, event_id),
            )
            conn.commit()
            return session_id

    def update_event_related(
        self,
        event_id: int,
        *,
        related_task_id: int | None = None,
        related_decision_id: int | None = None,
        related_blocker_id: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        now = utc_now()
        assignments = ["updated_at = ?"]
        params: list[Any] = [now]
        if related_task_id is not None:
            assignments.append("related_task_id = ?")
            params.append(related_task_id)
        if related_decision_id is not None:
            assignments.append("related_decision_id = ?")
            params.append(related_decision_id)
        if related_blocker_id is not None:
            assignments.append("related_blocker_id = ?")
            params.append(related_blocker_id)
        if metadata is not None:
            assignments.append("metadata_json = ?")
            params.append(json.dumps(metadata, sort_keys=True))
        params.append(event_id)
        with self.connect() as conn:
            conn.execute(f"UPDATE events SET {', '.join(assignments)} WHERE id = ?", params)
            conn.commit()

    def create_event_link(
        self,
        project_id: int,
        event_id: int,
        linked_kind: str,
        linked_id: int,
        relationship: str = "related",
    ) -> int:
        now = utc_now()
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO event_links (
                    project_id, event_id, linked_kind, linked_id, relationship, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (project_id, event_id, linked_kind, linked_id, relationship, now),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def find_similar_open_task(self, project_id: int, title: str) -> dict[str, Any] | None:
        target = normalize_text(title)
        if not target:
            return None
        rows = self.query_all(
            """
            SELECT * FROM tasks
            WHERE project_id = ? AND status IN ('open', 'blocked')
            ORDER BY created_at DESC
            """,
            (project_id,),
        )
        for row in rows:
            existing = normalize_text(row.get("title"))
            if existing == target or existing in target or target in existing:
                return row
        return None

    def find_similar_decision(self, project_id: int, title: str, summary: str | None = None) -> dict[str, Any] | None:
        target_title = normalize_text(title)
        target_summary = normalize_text(summary)
        if not target_title:
            return None
        rows = self.query_all(
            """
            SELECT * FROM decisions
            WHERE project_id = ?
            ORDER BY created_at DESC
            LIMIT 100
            """,
            (project_id,),
        )
        for row in rows:
            existing_title = normalize_text(row.get("title"))
            existing_summary = normalize_text(row.get("summary"))
            if existing_title == target_title and (not target_summary or existing_summary == target_summary):
                return row
            if existing_title and (existing_title in target_title or target_title in existing_title):
                return row
        return None

    def get_event(self, event_id: int) -> dict[str, Any] | None:
        self.initialize()
        return self.query_one(
            """
            SELECT e.*, p.slug AS project_slug, p.name AS project_name
            FROM events e
            JOIN projects p ON p.id = e.project_id
            WHERE e.id = ?
            """,
            (event_id,),
        )

    def list_recent_changes_since(
        self,
        project: str | int | None = None,
        since_event_id: int | None = None,
        since_timestamp: str | None = None,
        source_filter: str | list[str] | None = None,
        event_type_filter: str | list[str] | None = None,
        include_consumed: bool = False,
        consumer_agent: str | None = None,
        limit: int = 50,
        order: str = "asc",
    ) -> list[dict[str, Any]]:
        self.initialize()
        params: list[Any] = []
        where = ["1 = 1"]
        if project:
            project_row = self.get_project(project)
            if project_row is None:
                return []
            where.append("e.project_id = ?")
            params.append(project_row["id"])
        if since_event_id is not None:
            where.append("e.id > ?")
            params.append(int(since_event_id))
        if since_timestamp:
            where.append("e.created_at > ?")
            params.append(since_timestamp)

        def add_filter(column: str, value: str | list[str]) -> None:
            values = [value] if isinstance(value, str) else [str(item) for item in value]
            if not values:
                return
            where.append(f"{column} IN ({', '.join('?' for _ in values)})")
            params.extend(values)

        if source_filter:
            add_filter("e.source", source_filter)
        if event_type_filter:
            add_filter("e.event_type", event_type_filter)
        if consumer_agent and not include_consumed:
            where.append(
                """
                NOT EXISTS (
                    SELECT 1 FROM agent_event_consumption c
                    WHERE c.event_id = e.id AND c.consumer_agent = ?
                )
                """
            )
            params.append(consumer_agent)

        order_clause = "ASC" if order.lower() in {"asc", "chronological"} else "DESC"
        params.append(max(1, min(int(limit), 200)))
        return self.query_all(
            f"""
            SELECT e.*, p.slug AS project_slug, p.name AS project_name
            FROM events e
            JOIN projects p ON p.id = e.project_id
            WHERE {' AND '.join(where)}
            ORDER BY e.id {order_clause}
            LIMIT ?
            """,
            params,
        )

    def mark_events_consumed(
        self,
        event_ids: list[int],
        consumer_agent: str,
        notes: str | None = None,
        action_taken: str | None = None,
        project: str | int | None = None,
    ) -> dict[str, Any]:
        self.initialize()
        normalized_ids = sorted({int(event_id) for event_id in event_ids})
        if not normalized_ids:
            return {"consumed_event_ids": [], "already_consumed_event_ids": [], "cursors": []}

        project_row = self.get_project(project) if project else None
        placeholders = ", ".join("?" for _ in normalized_ids)
        params: list[Any] = [*normalized_ids]
        project_clause = ""
        if project_row is not None:
            project_clause = " AND project_id = ?"
            params.append(project_row["id"])

        with self.connect() as conn:
            event_rows = conn.execute(
                f"SELECT id, project_id FROM events WHERE id IN ({placeholders}){project_clause} ORDER BY id",
                params,
            ).fetchall()
            if len(event_rows) != len(normalized_ids):
                found = {int(row["id"]) for row in event_rows}
                missing = sorted(set(normalized_ids) - found)
                raise ValueError(f"Event ids were not found: {missing}")

            existing = {
                int(row["event_id"])
                for row in conn.execute(
                    f"""
                    SELECT event_id FROM agent_event_consumption
                    WHERE consumer_agent = ? AND event_id IN ({placeholders})
                    """,
                    [consumer_agent, *normalized_ids],
                ).fetchall()
            }

            now = utc_now()
            for row in event_rows:
                conn.execute(
                    """
                    INSERT INTO agent_event_consumption (
                        event_id, consumer_agent, consumed_at, action_taken, notes
                    )
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(event_id, consumer_agent) DO UPDATE SET
                        action_taken = COALESCE(excluded.action_taken, agent_event_consumption.action_taken),
                        notes = COALESCE(excluded.notes, agent_event_consumption.notes)
                    """,
                    (row["id"], consumer_agent, now, action_taken, notes),
                )

            cursors: list[dict[str, Any]] = []
            project_ids = sorted({int(row["project_id"]) for row in event_rows})
            for project_id in project_ids:
                last_event_id = max(int(row["id"]) for row in event_rows if int(row["project_id"]) == project_id)
                current = conn.execute(
                    """
                    SELECT last_event_id FROM agent_project_cursors
                    WHERE project_id = ? AND consumer_agent = ?
                    """,
                    (project_id, consumer_agent),
                ).fetchone()
                if current is not None and int(current["last_event_id"]) > last_event_id:
                    last_event_id = int(current["last_event_id"])
                conn.execute(
                    """
                    INSERT INTO agent_project_cursors (
                        project_id, consumer_agent, last_event_id, updated_at
                    )
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(project_id, consumer_agent) DO UPDATE SET
                        last_event_id = excluded.last_event_id,
                        updated_at = excluded.updated_at
                    """,
                    (project_id, consumer_agent, last_event_id, now),
                )
                project_info = conn.execute("SELECT slug, name FROM projects WHERE id = ?", (project_id,)).fetchone()
                cursors.append(
                    {
                        "project_id": project_id,
                        "project_slug": project_info["slug"],
                        "project_name": project_info["name"],
                        "consumer_agent": consumer_agent,
                        "last_event_id": last_event_id,
                        "updated_at": now,
                    }
                )
            conn.commit()

        return {
            "consumed_event_ids": normalized_ids,
            "already_consumed_event_ids": sorted(existing),
            "cursors": cursors,
        }

    def get_project_cursor(self, project: str | int, consumer_agent: str) -> dict[str, Any] | None:
        project_row = self.get_project(project)
        if project_row is None:
            return None
        return self.query_one(
            """
            SELECT c.*, p.slug AS project_slug, p.name AS project_name
            FROM agent_project_cursors c
            JOIN projects p ON p.id = c.project_id
            WHERE c.project_id = ? AND c.consumer_agent = ?
            """,
            (project_row["id"], consumer_agent),
        )

    def assigned_tasks_for_agent(
        self,
        agent: str,
        project: str | int | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        self.initialize()
        params: list[Any] = [agent]
        owner_clause = "t.owner = ?"
        if "openclaw" in agent.lower():
            owner_clause = "(t.owner = ? OR t.owner = 'any-openclaw')"
        elif "codex" in agent.lower():
            owner_clause = "(t.owner = ? OR t.owner = 'any-codex')"

        project_clause = ""
        if project:
            project_row = self.get_project(project)
            if project_row is None:
                return []
            project_clause = " AND t.project_id = ?"
            params.append(project_row["id"])
        params.append(max(1, min(int(limit), 100)))
        return self.query_all(
            f"""
            SELECT t.*, p.slug AS project_slug, p.name AS project_name
            FROM tasks t
            JOIN projects p ON p.id = t.project_id
            WHERE t.status IN ('open', 'blocked') AND {owner_clause}{project_clause}
            ORDER BY
                CASE COALESCE(t.priority, '')
                    WHEN 'urgent' THEN 1
                    WHEN 'high' THEN 2
                    WHEN 'medium' THEN 3
                    WHEN 'low' THEN 4
                    ELSE 5
                END,
                COALESCE(t.due_date, '9999-12-31'),
                t.created_at DESC
            LIMIT ?
            """,
            params,
        )

    def open_blockers(self, project: str | int | None = None, limit: int = 20) -> list[dict[str, Any]]:
        self.initialize()
        params: list[Any] = []
        project_clause = ""
        if project:
            project_row = self.get_project(project)
            if project_row is None:
                return []
            project_clause = " AND b.project_id = ?"
            params.append(project_row["id"])
        params.append(max(1, min(int(limit), 100)))
        return self.query_all(
            f"""
            SELECT b.*, p.slug AS project_slug, p.name AS project_name
            FROM blockers b
            JOIN projects p ON p.id = b.project_id
            WHERE b.status = 'open'{project_clause}
            ORDER BY b.created_at DESC
            LIMIT ?
            """,
            params,
        )

    def recent_decisions(self, project: str | int | None = None, limit: int = 20) -> list[dict[str, Any]]:
        self.initialize()
        params: list[Any] = []
        project_clause = ""
        if project:
            project_row = self.get_project(project)
            if project_row is None:
                return []
            project_clause = " WHERE d.project_id = ?"
            params.append(project_row["id"])
        params.append(max(1, min(int(limit), 100)))
        return self.query_all(
            f"""
            SELECT d.*, p.slug AS project_slug, p.name AS project_name
            FROM decisions d
            JOIN projects p ON p.id = d.project_id
            {project_clause}
            ORDER BY d.created_at DESC
            LIMIT ?
            """,
            params,
        )

    def stale_tasks_for_agent(self, agent: str, project: str | int | None = None, limit: int = 20) -> list[dict[str, Any]]:
        today = today_utc()
        return [
            row
            for row in self.assigned_tasks_for_agent(agent=agent, project=project, limit=limit)
            if row.get("status") == "blocked" or (row.get("due_date") and str(row["due_date"]) < today)
        ]

    def upsert_project_brief(
        self,
        project_id: int,
        summary_delta: str,
        status: str | None = None,
        current_state: str | None = None,
        next_steps: list[Any] | None = None,
        risks: list[Any] | None = None,
        source_event_ids: list[int] | None = None,
        sensitivity: str = "internal",
    ) -> dict[str, Any]:
        now = utc_now()
        with self.connect() as conn:
            existing = conn.execute("SELECT * FROM project_briefs WHERE project_id = ?", (project_id,)).fetchone()
            if existing is None:
                summary = summary_delta.strip()
                conn.execute(
                    """
                    INSERT INTO project_briefs (
                        project_id, summary, status, current_state, next_steps_json,
                        risks_json, source_event_ids_json, sensitivity, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        project_id,
                        summary,
                        status,
                        current_state,
                        json.dumps(next_steps or [], sort_keys=True),
                        json.dumps(risks or [], sort_keys=True),
                        json.dumps(source_event_ids or [], sort_keys=True),
                        sensitivity,
                        now,
                        now,
                    ),
                )
            else:
                existing_summary = str(existing["summary"] or "").strip()
                summary = existing_summary
                if summary_delta.strip():
                    dated_delta = f"{today_utc()}: {summary_delta.strip()}"
                    summary = f"{existing_summary}\n\n{dated_delta}" if existing_summary else dated_delta
                conn.execute(
                    """
                    UPDATE project_briefs SET
                        summary = ?,
                        status = COALESCE(?, status),
                        current_state = COALESCE(?, current_state),
                        next_steps_json = COALESCE(?, next_steps_json),
                        risks_json = COALESCE(?, risks_json),
                        source_event_ids_json = COALESCE(?, source_event_ids_json),
                        sensitivity = ?,
                        updated_at = ?
                    WHERE project_id = ?
                    """,
                    (
                        summary,
                        status,
                        current_state,
                        json.dumps(next_steps, sort_keys=True) if next_steps is not None else None,
                        json.dumps(risks, sort_keys=True) if risks is not None else None,
                        json.dumps(source_event_ids, sort_keys=True) if source_event_ids is not None else None,
                        sensitivity,
                        now,
                        project_id,
                    ),
                )
            conn.commit()
        brief = self.get_project_brief_record(project_id)
        if brief is None:
            raise RuntimeError("Project brief update failed")
        return brief

    def get_project_brief_record(self, project: str | int) -> dict[str, Any] | None:
        project_row = self.get_project(project)
        if project_row is None:
            return None
        return self.query_one(
            """
            SELECT b.*, p.slug AS project_slug, p.name AS project_name
            FROM project_briefs b
            JOIN projects p ON p.id = b.project_id
            WHERE b.project_id = ?
            """,
            (project_row["id"],),
        )

    def list_projects(self) -> list[dict[str, Any]]:
        self.initialize()
        return self.query_all(
            """
            SELECT p.*,
                   COUNT(DISTINCT t.id) AS open_tasks,
                   COUNT(DISTINCT b.id) AS open_blockers,
                   MAX(e.created_at) AS last_event_at
            FROM projects p
            LEFT JOIN tasks t ON t.project_id = p.id AND t.status IN ('open', 'blocked')
            LEFT JOIN blockers b ON b.project_id = p.id AND b.status = 'open'
            LEFT JOIN events e ON e.project_id = p.id
            GROUP BY p.id
            ORDER BY COALESCE(last_event_at, p.updated_at) DESC
            """
        )

    def list_open_tasks(self, project: str | int | None = None) -> list[dict[str, Any]]:
        self.initialize()
        params: list[Any] = []
        where = "t.status IN ('open', 'blocked')"
        if project:
            project_row = self.get_project(project)
            if project_row is None:
                return []
            where += " AND t.project_id = ?"
            params.append(project_row["id"])

        return self.query_all(
            f"""
            SELECT t.*, p.slug AS project_slug, p.name AS project_name
            FROM tasks t
            JOIN projects p ON p.id = t.project_id
            WHERE {where}
            ORDER BY
                CASE COALESCE(t.priority, '')
                    WHEN 'urgent' THEN 1
                    WHEN 'high' THEN 2
                    WHEN 'medium' THEN 3
                    WHEN 'low' THEN 4
                    ELSE 5
                END,
                COALESCE(t.due_date, '9999-12-31'),
                t.created_at DESC
            """,
            params,
        )

    def recent_events(self, limit: int = 20, project: str | int | None = None) -> list[dict[str, Any]]:
        self.initialize()
        params: list[Any] = []
        where = "1 = 1"
        if project:
            project_row = self.get_project(project)
            if project_row is None:
                return []
            where += " AND e.project_id = ?"
            params.append(project_row["id"])
        params.append(max(1, min(int(limit), 100)))
        return self.query_all(
            f"""
            SELECT e.*, p.slug AS project_slug, p.name AS project_name
            FROM events e
            JOIN projects p ON p.id = e.project_id
            WHERE {where}
            ORDER BY e.created_at DESC
            LIMIT ?
            """,
            params,
        )

    def events_for_day(self, day: str) -> list[dict[str, Any]]:
        self.initialize()
        return self.query_all(
            """
            SELECT e.*, p.slug AS project_slug, p.name AS project_name
            FROM events e
            JOIN projects p ON p.id = e.project_id
            WHERE substr(e.created_at, 1, 10) = ?
            ORDER BY e.created_at DESC
            """,
            (day,),
        )

    def project_state(self, project: str | int) -> dict[str, Any] | None:
        project_row = self.get_project(project)
        if project_row is None:
            return None
        project_id = project_row["id"]
        return {
            "project": project_row,
            "project_brief": self.get_project_brief_record(project_id),
            "recent_events": self.recent_events(limit=10, project=project_id),
            "open_tasks": self.query_all(
                "SELECT * FROM tasks WHERE project_id = ? AND status IN ('open', 'blocked') ORDER BY created_at DESC",
                (project_id,),
            ),
            "decisions": self.query_all(
                "SELECT * FROM decisions WHERE project_id = ? ORDER BY created_at DESC LIMIT 50",
                (project_id,),
            ),
            "open_blockers": self.query_all(
                "SELECT * FROM blockers WHERE project_id = ? AND status = 'open' ORDER BY created_at DESC",
                (project_id,),
            ),
            "references": self.query_all(
                'SELECT * FROM "references" WHERE project_id = ? ORDER BY created_at DESC LIMIT 50',
                (project_id,),
            ),
            "codex_sessions": self.query_all(
                "SELECT * FROM codex_sessions WHERE project_id = ? ORDER BY created_at DESC LIMIT 20",
                (project_id,),
            ),
        }

    def update_task_status(self, task_id: int, status: str) -> dict[str, Any]:
        allowed = {"open", "blocked", "done"}
        if status not in allowed:
            raise ValueError(f"Task status must be one of: {', '.join(sorted(allowed))}")

        now = utc_now()
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT t.*, p.slug AS project_slug, p.name AS project_name
                FROM tasks t
                JOIN projects p ON p.id = t.project_id
                WHERE t.id = ?
                """,
                (task_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"Task {task_id} was not found")

            conn.execute(
                "UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?",
                (status, now, task_id),
            )
            cursor = conn.execute(
                """
                INSERT INTO events (
                    project_id, event_type, source, title, summary, sensitivity,
                    metadata_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["project_id"],
                    "task_status",
                    "workstream",
                    f"Task {task_id} marked {status}",
                    row["title"],
                    row["sensitivity"],
                    json.dumps({"task_id": task_id, "status": status}, sort_keys=True),
                    now,
                    now,
                ),
            )
            conn.commit()
            updated = self.query_one(
                """
                SELECT t.*, p.slug AS project_slug, p.name AS project_name
                FROM tasks t
                JOIN projects p ON p.id = t.project_id
                WHERE t.id = ?
                """,
                (task_id,),
            )
            if updated is None:
                raise RuntimeError("Task update failed")
            updated["event_id"] = int(cursor.lastrowid)
            return updated

    def update_blocker_status(self, blocker_id: int, status: str) -> dict[str, Any]:
        allowed = {"open", "resolved"}
        if status not in allowed:
            raise ValueError(f"Blocker status must be one of: {', '.join(sorted(allowed))}")

        now = utc_now()
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT b.*, p.slug AS project_slug, p.name AS project_name
                FROM blockers b
                JOIN projects p ON p.id = b.project_id
                WHERE b.id = ?
                """,
                (blocker_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"Blocker {blocker_id} was not found")

            conn.execute(
                "UPDATE blockers SET status = ?, updated_at = ? WHERE id = ?",
                (status, now, blocker_id),
            )
            cursor = conn.execute(
                """
                INSERT INTO events (
                    project_id, event_type, source, title, summary, sensitivity,
                    metadata_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["project_id"],
                    "blocker_status",
                    "workstream",
                    f"Blocker {blocker_id} marked {status}",
                    row["title"],
                    row["sensitivity"],
                    json.dumps({"blocker_id": blocker_id, "status": status}, sort_keys=True),
                    now,
                    now,
                ),
            )
            conn.commit()
            updated = self.query_one(
                """
                SELECT b.*, p.slug AS project_slug, p.name AS project_name
                FROM blockers b
                JOIN projects p ON p.id = b.project_id
                WHERE b.id = ?
                """,
                (blocker_id,),
            )
            if updated is None:
                raise RuntimeError("Blocker update failed")
            updated["event_id"] = int(cursor.lastrowid)
            return updated

    def health(self) -> dict[str, Any]:
        self.initialize()
        with self.connect() as conn:
            conn.execute("CREATE TEMP TABLE IF NOT EXISTS workstream_healthcheck (ok INTEGER)")
            conn.execute("INSERT INTO workstream_healthcheck (ok) VALUES (1)")
            conn.execute("DELETE FROM workstream_healthcheck")
            project_count = conn.execute("SELECT COUNT(*) AS count FROM projects").fetchone()["count"]
            event_count = conn.execute("SELECT COUNT(*) AS count FROM events").fetchone()["count"]
        return {
            "status": "ok",
            "database": str(self.path),
            "readable": True,
            "writable": True,
            "project_count": int(project_count),
            "event_count": int(event_count),
        }

    def search(self, query: str, project: str | int | None = None, limit: int = 20) -> list[dict[str, Any]]:
        self.initialize()
        query_like = f"%{query.strip()}%"
        params: list[Any] = []
        project_clause = ""
        if project:
            project_row = self.get_project(project)
            if project_row is None:
                return []
            project_clause = " AND p.id = ?"
            params.append(project_row["id"])

        limit_value = max(1, min(int(limit), 100))
        union_params: list[Any] = []
        for _ in range(6):
            union_params.extend([query_like, query_like, *params])
        union_params.append(limit_value)

        return self.query_all(
            f"""
            SELECT * FROM (
                SELECT 'event' AS kind, e.id AS id, p.slug AS project, e.title AS title,
                       e.summary AS snippet, e.created_at AS created_at, e.sensitivity AS sensitivity
                FROM events e JOIN projects p ON p.id = e.project_id
                WHERE (e.title LIKE ? OR e.summary LIKE ? OR e.body LIKE ? OR e.rationale LIKE ?){project_clause}
                UNION ALL
                SELECT 'task', t.id, p.slug, t.title, t.description, t.created_at, t.sensitivity
                FROM tasks t JOIN projects p ON p.id = t.project_id
                WHERE (t.title LIKE ? OR t.description LIKE ?){project_clause}
                UNION ALL
                SELECT 'decision', d.id, p.slug, d.title, d.summary, d.created_at, d.sensitivity
                FROM decisions d JOIN projects p ON p.id = d.project_id
                WHERE (d.title LIKE ? OR d.summary LIKE ? OR d.rationale LIKE ?){project_clause}
                UNION ALL
                SELECT 'blocker', b.id, p.slug, b.title, b.description, b.created_at, b.sensitivity
                FROM blockers b JOIN projects p ON p.id = b.project_id
                WHERE (b.title LIKE ? OR b.description LIKE ?){project_clause}
                UNION ALL
                SELECT 'reference', r.id, p.slug, COALESCE(r.label, r.uri), r.description, r.created_at, r.sensitivity
                FROM "references" r JOIN projects p ON p.id = r.project_id
                WHERE (r.uri LIKE ? OR r.label LIKE ? OR r.description LIKE ?){project_clause}
                UNION ALL
                SELECT 'codex_session', c.id, p.slug, c.goal, c.tests_summary, c.created_at, c.sensitivity
                FROM codex_sessions c JOIN projects p ON p.id = c.project_id
                WHERE (c.goal LIKE ? OR c.status LIKE ? OR c.tests_summary LIKE ?
                       OR c.changed_files_json LIKE ? OR c.commands_run_json LIKE ?){project_clause}
            )
            ORDER BY created_at DESC
            LIMIT ?
            """,
            _search_params(query_like, params, limit_value),
        )


def _search_params(query_like: str, project_params: list[Any], limit_value: int) -> list[Any]:
    params: list[Any] = []
    specs = [4, 2, 3, 2, 3, 5]
    for count in specs:
        params.extend([query_like] * count)
        params.extend(project_params)
    params.append(limit_value)
    return params
