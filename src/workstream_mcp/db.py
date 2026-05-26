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


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def today_utc() -> str:
    return datetime.now(UTC).date().isoformat()


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "project"


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}


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
        sensitivity: str = "internal",
        metadata: dict[str, Any] | None = None,
    ) -> int:
        now = utc_now()
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO events (
                    project_id, event_type, source, title, summary, sensitivity,
                    metadata_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    event_type,
                    source,
                    title,
                    summary,
                    sensitivity,
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
                WHERE (e.title LIKE ? OR e.summary LIKE ?){project_clause}
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
    specs = [2, 2, 3, 2, 3, 5]
    for count in specs:
        params.extend([query_like] * count)
        params.extend(project_params)
    params.append(limit_value)
    return params
