from __future__ import annotations

import json
from pathlib import Path

from workstream_mcp.cli import _load_capture_file, main
from workstream_mcp.db import WorkstreamDB
from workstream_mcp.export import export_markdown
from workstream_mcp.resources import render_open_tasks, render_projects
from workstream_mcp.safety import SecretDetectedError, assert_safe_to_store
from workstream_mcp.tools import capture_handoff, record_codex_session, search_workstream


def test_initialize_database_creates_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "workstream.db"
    db = WorkstreamDB(db_path)
    db.initialize()

    tables = {
        row["name"]
        for row in db.query_all("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert {"projects", "events", "tasks", "decisions", "blockers", "references", "codex_sessions"} <= tables


def test_capture_handoff_creates_project_event_and_related_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "workstream.db"
    result = capture_handoff(
        source="chatgpt",
        project="Demo Project",
        title="Handoff",
        summary="A useful summary",
        decisions=["Use SQLite"],
        next_actions=[{"title": "Write tests", "priority": "high"}],
        blockers=["Need MCP client validation"],
        references=[{"label": "docs", "uri": "https://example.test/docs"}],
        sensitivity="internal",
        db_path=db_path,
    )

    db = WorkstreamDB(db_path)
    assert result["project_slug"] == "demo-project"
    assert len(result["task_ids"]) == 1
    assert db.query_one("SELECT COUNT(*) AS count FROM events")["count"] == 1
    assert db.query_one("SELECT COUNT(*) AS count FROM tasks")["count"] == 1
    assert db.query_one("SELECT COUNT(*) AS count FROM decisions")["count"] == 1
    assert db.query_one("SELECT COUNT(*) AS count FROM blockers")["count"] == 1
    assert db.query_one('SELECT COUNT(*) AS count FROM "references"')["count"] == 1


def test_record_codex_session_creates_session_tasks_decisions_and_blockers(tmp_path: Path) -> None:
    db_path = tmp_path / "workstream.db"
    result = record_codex_session(
        project="Demo Project",
        repo_path="/tmp/demo",
        host="local",
        goal="Implement a thing",
        status="done",
        changed_files=["src/demo.py"],
        commands_run=["pytest"],
        tests_summary="pytest passed",
        decisions=[{"title": "Keep it small", "summary": "Avoid extra scope"}],
        next_actions=["Ship it"],
        blockers=["None"],
        db_path=db_path,
    )

    db = WorkstreamDB(db_path)
    assert result["codex_session_id"] == 1
    session = db.query_one("SELECT * FROM codex_sessions WHERE id = ?", (result["codex_session_id"],))
    assert json.loads(session["changed_files_json"]) == ["src/demo.py"]
    assert db.query_one("SELECT COUNT(*) AS count FROM tasks")["count"] == 1
    assert db.query_one("SELECT COUNT(*) AS count FROM decisions")["count"] == 1
    assert db.query_one("SELECT COUNT(*) AS count FROM blockers")["count"] == 1


def test_resources_render_projects_and_open_tasks(tmp_path: Path) -> None:
    db_path = tmp_path / "workstream.db"
    capture_handoff(
        source="chatgpt",
        project="Demo Project",
        title="Handoff",
        summary="Summary",
        next_actions=["Do the thing"],
        db_path=db_path,
    )

    assert "Demo Project" in render_projects(db_path=db_path)
    assert "Do the thing" in render_open_tasks(db_path=db_path)


def test_markdown_capture_parser_accepts_prompt_style_labels(tmp_path: Path) -> None:
    handoff = tmp_path / "handoff.md"
    handoff.write_text(
        """Project: Markdown Project
Title: Markdown handoff
Summary: This came from a prompt-style template.

Decisions:
- Keep Markdown human readable

Next Actions:
- Capture this into SQLite

Blockers:
- Validate with MCP client

References:
- op://Engineering/Workstream/reference

Sensitivity: internal
""",
        encoding="utf-8",
    )

    data = _load_capture_file(handoff, source=None, project=None)
    assert data["project"] == "Markdown Project"
    assert data["title"] == "Markdown handoff"
    assert data["decisions"] == ["Keep Markdown human readable"]
    assert data["next_actions"] == ["Capture this into SQLite"]
    assert data["references"] == ["op://Engineering/Workstream/reference"]


def test_markdown_export_writes_project_and_daily_files(tmp_path: Path) -> None:
    db_path = tmp_path / "workstream.db"
    export_dir = tmp_path / "exports"
    capture_handoff(
        source="chatgpt",
        project="Demo Project",
        title="Handoff",
        summary="Summary",
        next_actions=["Do the thing"],
        db_path=db_path,
    )

    result = export_markdown(db_path=db_path, export_dir=export_dir)
    project_path = Path(result["projects"][0])
    daily_path = Path(result["daily"][0])
    assert project_path.exists()
    assert daily_path.exists()
    assert "Demo Project" in project_path.read_text(encoding="utf-8")
    assert "Workstream Today" in daily_path.read_text(encoding="utf-8")


def test_secret_like_input_is_rejected_and_references_are_allowed() -> None:
    assert_safe_to_store({"reference": "op://Engineering/OpenAI API key/credential"})
    try:
        assert_safe_to_store({"reference": "op://Engineering/OpenAI API key/credential sk-abcdefghijklmnopqrstuvwxyz123456"})
    except SecretDetectedError:
        pass
    else:
        raise AssertionError("Expected SecretDetectedError for secret appended to reference")

    try:
        assert_safe_to_store({"note": "api_key=sk-abcdefghijklmnopqrstuvwxyz123456"})
    except SecretDetectedError as exc:
        assert "Secret-like content was rejected" in str(exc)
    else:
        raise AssertionError("Expected SecretDetectedError")


def test_search_workstream(tmp_path: Path) -> None:
    db_path = tmp_path / "workstream.db"
    capture_handoff(
        source="chatgpt",
        project="Demo Project",
        title="Handoff",
        summary="Need searchable context",
        next_actions=["Write search tests"],
        db_path=db_path,
    )

    result = search_workstream("searchable", db_path=db_path)
    assert result["results"]
    assert result["results"][0]["project"] == "demo-project"


def test_cli_init_capture_and_list(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "workstream.db"
    export_dir = tmp_path / "exports"
    handoff = tmp_path / "handoff.json"
    handoff.write_text(
        json.dumps(
            {
                "source": "chatgpt",
                "project": "CLI Project",
                "title": "CLI handoff",
                "summary": "Captured from CLI",
                "decisions": [],
                "next_actions": ["Check CLI output"],
                "blockers": [],
                "references": [],
                "sensitivity": "internal"
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("WORKSTREAM_DB_PATH", str(db_path))
    monkeypatch.setenv("WORKSTREAM_EXPORT_DIR", str(export_dir))

    assert main(["init"]) == 0
    assert main(["capture", "--file", str(handoff)]) == 0
    assert main(["list-projects"]) == 0
    assert main(["list-tasks"]) == 0
    assert main(["export-markdown"]) == 0
    assert (export_dir / "projects" / "cli-project.md").exists()
