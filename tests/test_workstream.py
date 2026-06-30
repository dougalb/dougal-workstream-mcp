from __future__ import annotations

import asyncio
import json
import time
import tomllib
from pathlib import Path

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from jsonschema import validate
from jwt.utils import base64url_encode
from starlette.testclient import TestClient

import workstream_mcp
from workstream_mcp import app_tools
from workstream_mcp.auth import READ_SCOPE, SENSITIVE_SCOPE, WRITE_SCOPE, JWTTokenVerifier, set_current_access_token
from workstream_mcp.config import WorkstreamConfig, load_config
from workstream_mcp.cli import _load_capture_file, main
from workstream_mcp.db import WorkstreamDB
from workstream_mcp.export import export_markdown
from workstream_mcp.resources import render_open_tasks, render_project_brief, render_projects
from workstream_mcp.safety import SecretDetectedError, assert_safe_to_store
from workstream_mcp.tools import (
    capture_handoff,
    create_or_update_project_brief,
    get_agent_digest,
    list_recent_changes_since,
    mark_event_consumed_by_agent,
    record_chatgpt_decision,
    record_codex_session,
    record_codex_session_summary,
    record_decision,
    record_openclaw_followup,
    record_session_handoff,
    search_workstream,
    update_blocker_status,
    update_task_status,
)


def _oauth_config(tmp_path: Path) -> tuple[WorkstreamConfig, rsa.RSAPrivateKey]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_numbers = key.public_key().public_numbers()
    jwks = {
        "keys": [
            {
                "kty": "RSA",
                "kid": "test-key",
                "use": "sig",
                "alg": "RS256",
                "n": base64url_encode(
                    public_numbers.n.to_bytes((public_numbers.n.bit_length() + 7) // 8, "big")
                ).decode("ascii"),
                "e": base64url_encode(
                    public_numbers.e.to_bytes((public_numbers.e.bit_length() + 7) // 8, "big")
                ).decode("ascii"),
            }
        ]
    }
    jwks_path = tmp_path / "jwks.json"
    jwks_path.write_text(json.dumps(jwks), encoding="utf-8")
    config = WorkstreamConfig(
        db_path=tmp_path / "workstream.db",
        export_dir=tmp_path / "exports",
        config_path=tmp_path / "workstream.yaml",
        log_dir=None,
        public_base_url="https://workstream.example.test",
        auth_mode="oauth",
        oauth_issuer="https://auth.example.test",
        oauth_audience="https://workstream.example.test",
        oauth_jwks_url=jwks_path.as_uri(),
        oauth_authorization_url="https://auth.example.test/authorize",
        oauth_token_url="https://auth.example.test/token",
        oauth_client_id=None,
        trust_proxy_headers=True,
        allowed_hosts=["workstream.example.test"],
    )
    return config, key


def _token(config: WorkstreamConfig, key: rsa.RSAPrivateKey, scope: str, **claims) -> str:
    payload = {
        "iss": config.oauth_issuer,
        "aud": config.oauth_audience,
        "sub": "user-1",
        "scope": scope,
        **claims,
    }
    return jwt.encode(payload, key, algorithm="RS256", headers={"kid": "test-key"})


def test_initialize_database_creates_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "workstream.db"
    db = WorkstreamDB(db_path)
    db.initialize()

    tables = {
        row["name"]
        for row in db.query_all("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert {
        "projects",
        "events",
        "event_links",
        "tasks",
        "decisions",
        "blockers",
        "references",
        "codex_sessions",
        "agent_event_consumption",
        "agent_project_cursors",
        "project_briefs",
    } <= tables


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


def test_record_session_handoff_creates_session_event_and_linked_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "workstream.db"
    result = record_session_handoff(
        project="Native Commands",
        source="chatgpt",
        source_agent="chatgpt-browser",
        title="Native command design",
        summary="Move cross-agent state into structured Workstream events.",
        decisions=[
            {
                "title": "Use semantic event capture",
                "summary": "Agents should consume Workstream events rather than raw browser state.",
                "rationale": "Structured events are durable and safer to share.",
            }
        ],
        tasks=[{"title": "Implement record_session_handoff", "priority": "high", "owner": "codex"}],
        blockers=[{"title": "Validate Apps SDK descriptor compatibility"}],
        references=[{"label": "Design note", "uri": "https://example.test/workstreams"}],
        next_actions=["Codex should inspect schema first."],
        open_questions=["Should project briefs be regenerated automatically?"],
        sensitivity="personal",
        db_path=db_path,
    )

    db = WorkstreamDB(db_path)
    event = db.get_event(result["event_id"])
    assert event["event_type"] == "handoff"
    assert event["source"] == "chatgpt"
    assert event["source_agent"] == "chatgpt-browser"
    assert event["sensitivity"] == "personal"
    assert len(result["created_event_ids"]) == 5
    assert len(result["decision_ids"]) == 1
    assert len(result["task_ids"]) == 1
    assert len(result["blocker_ids"]) == 1
    assert len(result["reference_ids"]) == 1
    assert db.query_one("SELECT COUNT(*) AS count FROM event_links")["count"] >= 4


def test_record_session_handoff_links_duplicate_open_tasks(tmp_path: Path) -> None:
    db_path = tmp_path / "workstream.db"
    first = record_session_handoff(
        project="Dedupe Project",
        source="chatgpt",
        title="First",
        summary="First handoff",
        tasks=["Implement durable event consumption"],
        db_path=db_path,
    )
    second = record_session_handoff(
        project="Dedupe Project",
        source="chatgpt",
        title="Second",
        summary="Second handoff",
        tasks=["Implement durable event consumption"],
        db_path=db_path,
    )

    db = WorkstreamDB(db_path)
    assert first["task_ids"] == [1]
    assert second["task_ids"] == []
    assert second["linked_existing_task_ids"] == [1]
    assert db.query_one("SELECT COUNT(*) AS count FROM tasks")["count"] == 1


def test_list_recent_changes_since_filters_by_project_and_consumption(tmp_path: Path) -> None:
    db_path = tmp_path / "workstream.db"
    a = record_session_handoff(
        project="Project A",
        source="chatgpt",
        title="A handoff",
        summary="A summary",
        tasks=["Task A"],
        db_path=db_path,
    )
    record_session_handoff(
        project="Project B",
        source="codex",
        title="B handoff",
        summary="B summary",
        tasks=["Task B"],
        db_path=db_path,
    )

    project_a_events = list_recent_changes_since(project="Project A", db_path=db_path)["events"]
    assert {event["project_slug"] for event in project_a_events} == {"project-a"}
    assert [event["id"] for event in project_a_events] == sorted(event["id"] for event in project_a_events)

    mark_once = mark_event_consumed_by_agent(
        consumer_agent="albert-openclaw",
        event_ids=a["created_event_ids"],
        action_taken="Created GTD follow-up.",
        db_path=db_path,
    )
    mark_twice = mark_event_consumed_by_agent(
        consumer_agent="albert-openclaw",
        event_ids=a["created_event_ids"],
        db_path=db_path,
    )
    remaining = list_recent_changes_since(
        project="Project A",
        consumer_agent="albert-openclaw",
        include_consumed=False,
        db_path=db_path,
    )
    assert mark_once["consumed_event_ids"] == a["created_event_ids"]
    assert mark_twice["already_consumed_event_ids"] == a["created_event_ids"]
    assert remaining["events"] == []


def test_record_openclaw_followup_creates_assigned_task_and_digest(tmp_path: Path) -> None:
    db_path = tmp_path / "workstream.db"
    result = record_openclaw_followup(
        project="Ops Project",
        title="Monitor shipping email",
        description="Watch inbox for the tracking number.",
        priority="high",
        assigned_agent="albert-openclaw",
        context="Needed for order follow-up.",
        db_path=db_path,
    )

    db = WorkstreamDB(db_path)
    task = db.query_one("SELECT * FROM tasks WHERE id = ?", (result["task_id"],))
    digest = get_agent_digest("albert-openclaw", project="Ops Project", db_path=db_path)
    assert task["owner"] == "albert-openclaw"
    assert result["event_id"] == task["event_id"]
    assert digest["assigned_open_tasks"][0]["title"] == "Monitor shipping email"


def test_record_codex_session_summary_records_implementation_notes(tmp_path: Path) -> None:
    db_path = tmp_path / "workstream.db"
    result = record_codex_session_summary(
        project="Implementation Project",
        title="Implemented event consumption",
        summary="Added event cursors and agent digests.",
        files_changed=["src/workstream_mcp/db.py"],
        commands_run=["pytest"],
        tests_run=["pytest tests/test_workstream.py"],
        implementation_notes=[
            {"title": "Added agent_event_consumption", "summary": "Tracks event consumption by agent."}
        ],
        followups=[{"title": "Document OpenClaw startup flow", "owner": "any-openclaw"}],
        sensitivity="internal",
        db_path=db_path,
    )

    db = WorkstreamDB(db_path)
    event_types = [row["event_type"] for row in db.query_all("SELECT event_type FROM events ORDER BY id")]
    assert "session_summary" in event_types
    assert "implementation_note" in event_types
    assert result["implementation_note_event_ids"]
    assert db.query_one("SELECT COUNT(*) AS count FROM codex_sessions")["count"] == 1


def test_chatgpt_decision_idempotency_and_project_brief_update(tmp_path: Path) -> None:
    db_path = tmp_path / "workstream.db"
    first = record_chatgpt_decision(
        project="Brief Project",
        title="Use Workstreams as coordination substrate",
        summary="Agents should coordinate through Workstreams events.",
        rationale="It avoids brittle transcript scraping.",
        sensitivity="internal",
        db_path=db_path,
    )
    second = record_chatgpt_decision(
        project="Brief Project",
        title="Use Workstreams as coordination substrate",
        summary="Agents should coordinate through Workstreams events.",
        rationale="It avoids brittle transcript scraping.",
        sensitivity="internal",
        db_path=db_path,
    )
    brief = create_or_update_project_brief(
        project="Brief Project",
        summary_delta="Event consumption is the current coordination model.",
        status="active",
        current_state="Implementing durable commands.",
        next_steps=["Run tests", "Update docs"],
        risks=["Avoid noisy event capture"],
        source_event_ids=[first["event_id"]],
        sensitivity="internal",
        db_path=db_path,
    )

    db = WorkstreamDB(db_path)
    assert first["created"] is True
    assert second["created"] is False
    assert db.query_one("SELECT COUNT(*) AS count FROM decisions")["count"] == 1
    assert brief["brief"]["status"] == "active"
    assert "Event consumption" in render_project_brief("Brief Project", db_path=db_path)


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


def test_project_brief_markdown_and_json(tmp_path: Path) -> None:
    db_path = tmp_path / "workstream.db"
    capture_handoff(
        source="chatgpt",
        project="Brief Project",
        title="Brief handoff",
        summary="Briefable context",
        next_actions=["Feed this to OpenClaw"],
        db_path=db_path,
    )

    markdown = render_project_brief("brief-project", db_path=db_path)
    payload = json.loads(render_project_brief("Brief Project", db_path=db_path, output_format="json"))
    assert "Brief Project" in markdown
    assert payload["project"]["slug"] == "brief-project"
    assert payload["open_tasks"][0]["title"] == "Feed this to OpenClaw"


def test_status_updates_create_events_and_filter_done_tasks(tmp_path: Path) -> None:
    db_path = tmp_path / "workstream.db"
    result = capture_handoff(
        source="chatgpt",
        project="Status Project",
        title="Status handoff",
        summary="Status context",
        next_actions=["Track me"],
        blockers=["Unblock me"],
        db_path=db_path,
    )

    task_update = update_task_status(result["task_ids"][0], "blocked", db_path=db_path)
    blocker_update = update_blocker_status(result["blocker_ids"][0], "resolved", db_path=db_path)
    assert task_update["status"] == "blocked"
    assert blocker_update["status"] == "resolved"
    assert "status: blocked" in render_open_tasks(db_path=db_path)

    update_task_status(result["task_ids"][0], "done", db_path=db_path)
    assert "Track me" not in render_open_tasks(db_path=db_path)

    db = WorkstreamDB(db_path)
    event_types = {row["event_type"] for row in db.query_all("SELECT event_type FROM events")}
    assert {"task_status", "blocker_status"} <= event_types


def test_record_codex_session_cli_from_file_and_brief(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "workstream.db"
    export_dir = tmp_path / "exports"
    session = tmp_path / "codex-session.json"
    session.write_text(
        json.dumps(
            {
                "project": "CLI Codex Project",
                "repo_path": "/tmp/repo",
                "host": "local",
                "goal": "Validate CLI ingestion",
                "status": "done",
                "changed_files": ["src/example.py"],
                "commands_run": ["pytest"],
                "tests_summary": "passed",
                "decisions": [],
                "next_actions": ["Read the brief"],
                "blockers": [],
                "sensitivity": "internal",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("WORKSTREAM_DB_PATH", str(db_path))
    monkeypatch.setenv("WORKSTREAM_EXPORT_DIR", str(export_dir))

    assert main(["record-codex-session", "--file", str(session)]) == 0
    assert main(["brief", "CLI Codex Project", "--format", "json"]) == 0
    db = WorkstreamDB(db_path)
    assert db.query_one("SELECT COUNT(*) AS count FROM codex_sessions")["count"] == 1
    assert db.get_project("CLI Codex Project")["slug"] == "cli-codex-project"


def test_cli_status_updates_and_doctor(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "workstream.db"
    export_dir = tmp_path / "exports"
    monkeypatch.setenv("WORKSTREAM_DB_PATH", str(db_path))
    monkeypatch.setenv("WORKSTREAM_EXPORT_DIR", str(export_dir))

    result = capture_handoff(
        source="chatgpt",
        project="CLI Status Project",
        title="Status handoff",
        summary="Summary",
        next_actions=["CLI task"],
        blockers=["CLI blocker"],
        db_path=db_path,
    )

    assert main(["update-task", str(result["task_ids"][0]), "--status", "done"]) == 0
    assert main(["update-blocker", str(result["blocker_ids"][0]), "--status", "resolved"]) == 0
    assert main(["doctor", "--format", "json"]) == 0
    db = WorkstreamDB(db_path)
    assert db.query_one("SELECT status FROM tasks WHERE id = ?", (result["task_ids"][0],))["status"] == "done"
    assert db.query_one("SELECT status FROM blockers WHERE id = ?", (result["blocker_ids"][0],))["status"] == "resolved"


def test_http_app_exposes_health_and_ready_routes() -> None:
    from workstream_mcp.server import create_http_app

    app = create_http_app()
    paths = {getattr(route, "path", "") for route in app.routes}
    assert "/healthz" in paths
    assert "/readyz" in paths
    assert "/mcp" in paths
    assert "/sse" in paths
    assert "/messages" in paths
    assert "/.well-known/oauth-protected-resource" in paths


def test_package_version_matches_project_metadata() -> None:
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    project_metadata = tomllib.loads(pyproject.read_text(encoding="utf-8"))

    assert workstream_mcp.__version__ == project_metadata["project"]["version"]


def test_mcp_initialization_advertises_workstream_version() -> None:
    from workstream_mcp.server import create_mcp

    initialization = create_mcp()._mcp_server.create_initialization_options()

    assert initialization.server_name == "dougal-workstream-mcp"
    assert initialization.server_version == workstream_mcp.__version__


def test_config_derives_and_accepts_allowed_hosts(tmp_path: Path, monkeypatch) -> None:
    from workstream_mcp.server import create_http_app

    monkeypatch.setenv("WORKSTREAM_CONFIG_PATH", str(tmp_path / "missing.yaml"))
    monkeypatch.setenv("WORKSTREAM_DB_PATH", str(tmp_path / "workstream.db"))
    monkeypatch.setenv("WORKSTREAM_EXPORT_DIR", str(tmp_path / "exports"))
    monkeypatch.setenv("WORKSTREAM_PUBLIC_BASE_URL", "http://10.10.10.20:8000")
    monkeypatch.setenv("WORKSTREAM_ALLOWED_HOSTS", "mcpgw.dmz.dougal.io,mcpgw.dmz.dougal.io:443")

    config = load_config()
    assert "10.10.10.20:8000" in config.allowed_hosts
    assert "10.10.10.20" in config.allowed_hosts
    assert "mcpgw.dmz.dougal.io" in config.allowed_hosts
    assert "mcpgw.dmz.dougal.io:443" in config.allowed_hosts

    with TestClient(create_http_app(config)) as client:
        response = client.get("/mcp", headers={"host": "10.10.10.20:8000"})
    assert response.status_code != 421


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


def test_oauth_metadata_and_missing_token_challenge(tmp_path: Path) -> None:
    from workstream_mcp.server import create_http_app

    config, _key = _oauth_config(tmp_path)
    client = TestClient(create_http_app(config))

    metadata = client.get("/.well-known/oauth-protected-resource")
    assert metadata.status_code == 200
    payload = metadata.json()
    assert payload["resource"] == "https://workstream.example.test"
    assert READ_SCOPE in payload["scopes_supported"]

    response = client.get("/mcp")
    assert response.status_code == 401
    assert "WWW-Authenticate" in response.headers
    assert "/.well-known/oauth-protected-resource" in response.headers["WWW-Authenticate"]


def test_oauth_token_verifier_rejects_invalid_expired_and_wrong_scope(tmp_path: Path) -> None:
    from workstream_mcp.server import create_http_app

    config, key = _oauth_config(tmp_path)
    verifier = JWTTokenVerifier(config)
    good = _token(config, key, f"{READ_SCOPE} {WRITE_SCOPE}", exp=int(time.time()) + 300)
    expired = _token(config, key, READ_SCOPE, exp=int(time.time()) - 300)

    access = asyncio.run(verifier.verify_token(good))
    assert access is not None
    assert READ_SCOPE in access.scopes
    assert asyncio.run(verifier.verify_token("not-a-jwt")) is None
    assert asyncio.run(verifier.verify_token(expired)) is None

    client = TestClient(create_http_app(config))
    wrong_scope = _token(config, key, WRITE_SCOPE, exp=int(time.time()) + 300)
    response = client.get("/mcp", headers={"Authorization": f"Bearer {wrong_scope}"})
    assert response.status_code == 401


def test_apps_sdk_tool_descriptors_include_security_annotations_and_output_schema(tmp_path: Path) -> None:
    from workstream_mcp.server import PROJECT_BRIEF_UI_URI, SEARCH_RESULTS_UI_URI, WRITE_REVIEW_UI_URI, create_mcp

    config, _key = _oauth_config(tmp_path)
    tools = {tool.name: tool for tool in asyncio.run(create_mcp(config).list_tools())}

    assert PROJECT_BRIEF_UI_URI == "ui://workstreams/project-brief-v4.html"
    assert SEARCH_RESULTS_UI_URI == "ui://workstreams/search-results-v4.html"
    assert WRITE_REVIEW_UI_URI == "ui://workstreams/write-review-v4.html"

    brief = tools["get_project_brief"]
    assert brief.securitySchemes == [{"type": "oauth2", "scopes": [READ_SCOPE]}]
    assert brief.meta["securitySchemes"] == brief.securitySchemes
    assert brief.meta["ui"]["resourceUri"] == PROJECT_BRIEF_UI_URI
    assert brief.meta["ui"]["visibility"] == ["model", "app"]
    assert brief.meta["openai/outputTemplate"] == PROJECT_BRIEF_UI_URI
    assert brief.meta["openai/visibility"] == "public"
    assert brief.meta["openai/widgetAccessible"] is True
    assert brief.meta["openai/toolInvocation/invoking"] == "Loading project brief..."
    assert brief.meta["openai/toolInvocation/invoked"] == "Project brief ready"
    assert brief.outputSchema["properties"]["project"]["type"] == "object"
    assert brief.annotations.readOnlyHint is True

    search = tools["search_workstream"]
    assert search.meta["ui"]["resourceUri"] == SEARCH_RESULTS_UI_URI
    assert search.meta["ui"]["visibility"] == ["model", "app"]
    assert search.meta["openai/outputTemplate"] == SEARCH_RESULTS_UI_URI
    assert search.meta["openai/visibility"] == "public"
    assert search.meta["openai/widgetAccessible"] is True
    assert search.annotations.readOnlyHint is True
    assert search.outputSchema["required"] == ["query", "count", "results"]

    recent_changes = tools["list_recent_changes_since"]
    assert recent_changes.meta["ui"]["resourceUri"] == SEARCH_RESULTS_UI_URI
    assert recent_changes.meta["openai/outputTemplate"] == SEARCH_RESULTS_UI_URI
    assert recent_changes.meta["openai/toolInvocation/invoked"] == "Recent changes ready"
    assert recent_changes.annotations.readOnlyHint is True

    digest = tools["get_agent_digest"]
    assert digest.meta["ui"]["resourceUri"] == SEARCH_RESULTS_UI_URI
    assert digest.meta["openai/outputTemplate"] == SEARCH_RESULTS_UI_URI
    assert digest.meta["openai/toolInvocation/invoked"] == "Digest ready"
    assert digest.annotations.readOnlyHint is True

    open_tasks = tools["list_open_tasks"]
    assert open_tasks.meta["ui"]["resourceUri"] == SEARCH_RESULTS_UI_URI
    assert open_tasks.meta["openai/outputTemplate"] == SEARCH_RESULTS_UI_URI
    assert open_tasks.meta["openai/toolInvocation/invoked"] == "Open tasks ready"
    assert open_tasks.annotations.readOnlyHint is True

    decision = tools["record_decision"]
    assert decision.meta["ui"]["resourceUri"] == WRITE_REVIEW_UI_URI
    assert decision.meta["ui"]["visibility"] == ["model", "app"]
    assert decision.meta["openai/widgetAccessible"] is True
    assert decision.meta["openai/toolInvocation/invoking"] == "Recording decision..."
    assert decision.annotations.readOnlyHint is False

    capture = tools["capture_handoff"]
    assert capture.securitySchemes == [{"type": "oauth2", "scopes": [READ_SCOPE, WRITE_SCOPE]}]
    assert capture.outputSchema["type"] == "object"
    assert capture.annotations.readOnlyHint is False
    assert capture.annotations.openWorldHint is False
    assert capture.annotations.destructiveHint is False
    assert capture.annotations.idempotentHint is False


def test_mcp_apps_ui_resources_are_registered_with_restrictive_metadata() -> None:
    from workstream_mcp.server import (
        LEGACY_PROJECT_BRIEF_WIDGET_URI,
        PROJECT_BRIEF_UI_ALIAS_URI,
        PROJECT_BRIEF_UI_URI,
        PROJECT_BRIEF_UI_V3_ALIAS_URI,
        PROJECT_BRIEF_UI_V2_ALIAS_URI,
        SEARCH_RESULTS_UI_ALIAS_URI,
        SEARCH_RESULTS_UI_URI,
        SEARCH_RESULTS_UI_V3_ALIAS_URI,
        SEARCH_RESULTS_UI_V2_ALIAS_URI,
        WRITE_REVIEW_UI_ALIAS_URI,
        WRITE_REVIEW_UI_URI,
        WRITE_REVIEW_UI_V3_ALIAS_URI,
        WRITE_REVIEW_UI_V2_ALIAS_URI,
        create_mcp,
    )

    mcp = create_mcp()
    resources = {str(resource.uri): resource for resource in asyncio.run(mcp.list_resources())}

    expected_uris = [
        PROJECT_BRIEF_UI_URI,
        SEARCH_RESULTS_UI_URI,
        WRITE_REVIEW_UI_URI,
        PROJECT_BRIEF_UI_V3_ALIAS_URI,
        SEARCH_RESULTS_UI_V3_ALIAS_URI,
        WRITE_REVIEW_UI_V3_ALIAS_URI,
        PROJECT_BRIEF_UI_V2_ALIAS_URI,
        SEARCH_RESULTS_UI_V2_ALIAS_URI,
        WRITE_REVIEW_UI_V2_ALIAS_URI,
        PROJECT_BRIEF_UI_ALIAS_URI,
        SEARCH_RESULTS_UI_ALIAS_URI,
        WRITE_REVIEW_UI_ALIAS_URI,
        LEGACY_PROJECT_BRIEF_WIDGET_URI,
    ]

    for uri in expected_uris:
        resource = resources[uri]
        assert resource.mimeType == "text/html;profile=mcp-app"
        assert resource.meta["ui"]["prefersBorder"] is True
        assert resource.meta["ui"]["csp"] == {"connectDomains": [], "resourceDomains": []}
        assert resource.meta["ui"]["domain"] == "https://mcpgw.dmz.dougal.io"
        assert resource.meta["openai/widgetPrefersBorder"] is True
        assert resource.meta["openai/widgetCSP"] == {"connect_domains": [], "resource_domains": []}
        assert resource.meta["openai/widgetDomain"] == "https://mcpgw.dmz.dougal.io"
        assert resource.meta["openai/widgetDescription"]
        contents = asyncio.run(mcp.read_resource(uri))
        assert contents[0].mime_type == "text/html;profile=mcp-app"
        assert "ui/notifications/tool-result" in contents[0].content
        assert "window.openai" in contents[0].content
        assert "openai:set_globals" in contents[0].content
        assert "toolOutput" in contents[0].content
        assert "mcp_tool_result" in contents[0].content
        assert "workstreams-ui" in contents[0].content
        assert "app-frame" in contents[0].content
        assert "--safe-block-start" in contents[0].content
        assert "overflow-x: hidden" in contents[0].content
        assert "<script src" not in contents[0].content
        assert "https://" not in contents[0].content
        assert "http://" not in contents[0].content


def test_search_results_ui_uses_compact_responsive_rows() -> None:
    from workstream_mcp import ui_resources

    html = ui_resources.search_results_html()

    assert 'class="workstreams-ui workstreams-search-results"' in html
    assert 'class="app-frame"' in html
    assert "padding: var(--safe-block-start) var(--safe-inline) var(--safe-block-end)" in html
    assert "result-row" in html
    assert "result-topline" in html
    assert "meta-row" in html
    assert "snippet-collapse" in html
    assert "Show full snippet" in html
    assert "normalizeSearchRows" in html
    assert "unconsumed_events" in html
    assert "assigned_open_tasks" in html
    assert "recent_decisions" in html
    assert "Recent changes" in html
    assert "Open tasks" in html
    assert 'event: "Events"' in html
    assert 'codex_session: "Codex sessions"' in html
    assert "<ul" not in html
    assert "<li" not in html
    assert "@media (max-width: 560px)" in html


def test_chatgpt_safe_project_brief_redacts_sensitive_rows_paths_and_commands(tmp_path: Path) -> None:
    db_path = tmp_path / "workstream.db"
    capture_handoff(
        source="chatgpt",
        project="Public Project",
        title="Internal handoff",
        summary="Internal summary",
        next_actions=["Visible task"],
        db_path=db_path,
    )
    capture_handoff(
        source="chatgpt",
        project="Public Project",
        title="Sensitive handoff",
        summary="Sensitive summary",
        next_actions=["Hidden sensitive task"],
        sensitivity="restricted",
        db_path=db_path,
    )
    record_codex_session(
        project="Public Project",
        repo_path="/tmp/private/repo",
        host="local",
        goal="Run checks in /tmp/private/repo",
        status="done",
        changed_files=["/tmp/private/repo/src/app.py"],
        commands_run=["pytest -k private"],
        tests_summary="pytest passed",
        db_path=db_path,
    )

    result = app_tools.get_project_brief("Public Project", db_path=db_path)
    serialized = json.dumps(result.structuredContent, sort_keys=True)
    assert "Visible task" in serialized
    assert "Hidden sensitive task" not in serialized
    assert "commands_run" not in serialized
    assert "repo_path" not in serialized
    assert "/tmp/private" not in serialized
    assert result.meta["omitted_sensitive_rows"] > 0


def test_chatgpt_safe_project_brief_can_include_sensitive_rows_with_scope(tmp_path: Path) -> None:
    from mcp.server.auth.provider import AccessToken
    from workstream_mcp.auth import reset_current_access_token

    db_path = tmp_path / "workstream.db"
    capture_handoff(
        source="chatgpt",
        project="Sensitive Project",
        title="Sensitive handoff",
        summary="Sensitive summary",
        next_actions=["Scoped sensitive task"],
        sensitivity="restricted",
        db_path=db_path,
    )

    token = set_current_access_token(AccessToken(token="test", client_id="test", scopes=[SENSITIVE_SCOPE]))
    try:
        result = app_tools.get_project_brief("Sensitive Project", db_path=db_path)
    finally:
        reset_current_access_token(token)
    assert "Scoped sensitive task" in json.dumps(result.structuredContent)


def test_project_brief_tool_result_is_portable_schema_valid_and_ui_hydratable(tmp_path: Path) -> None:
    from workstream_mcp.server import PROJECT_BRIEF_OUTPUT_SCHEMA

    db_path = tmp_path / "workstream.db"
    record_session_handoff(
        project="Apps Contract",
        source="chatgpt",
        title="Apps handoff",
        summary="Harden portable MCP contracts.",
        decisions=[{"title": "Keep UI optional", "summary": "Clients can ignore iframe rendering."}],
        tasks=[{"title": "Validate output schemas", "priority": "high"}],
        blockers=[{"title": "Need host verification"}],
        references=[{"label": "MCP Apps reference", "uri": "https://developers.openai.com/apps-sdk/reference"}],
        db_path=db_path,
    )
    record_codex_session_summary(
        project="Apps Contract",
        title="Implemented contract tests",
        summary="Added descriptor and resource assertions.",
        files_changed=["src/workstream_mcp/server.py"],
        tests_run=["pytest"],
        db_path=db_path,
    )
    create_or_update_project_brief(
        project="Apps Contract",
        summary_delta="Portable results are the primary contract.",
        status="active",
        current_state="Adding MCP Apps UI resources.",
        next_steps=["Run tests"],
        risks=["Avoid ChatGPT lock-in"],
        db_path=db_path,
    )

    result = app_tools.get_project_brief("Apps Contract", db_path=db_path)

    assert result.content
    assert "Project brief: Apps Contract" in result.content[0].text
    assert "Open tasks:" in result.content[0].text
    validate(instance=result.structuredContent, schema=PROJECT_BRIEF_OUTPUT_SCHEMA)
    assert result.structuredContent["project"]["slug"] == "apps-contract"
    assert result.structuredContent["open_tasks"]
    assert result.structuredContent["decisions"]
    assert result.structuredContent["open_blockers"]
    assert result.structuredContent["references"]
    assert result.structuredContent["codex_sessions"]
    assert result.meta["defaultView"] == "overview"
    assert result.meta["tasksById"]
    assert result.meta["decisionsById"]
    assert result.meta["blockersById"]
    assert result.meta["referencesById"]
    assert result.meta["sessionsById"]


def test_project_brief_empty_states_remain_useful_without_meta(tmp_path: Path) -> None:
    db_path = tmp_path / "workstream.db"
    record_decision(
        project="Empty State",
        title="Only decision recorded",
        summary="No open work exists yet.",
        rationale="This validates sparse project briefs.",
        db_path=db_path,
    )

    result = app_tools.get_project_brief("Empty State", db_path=db_path)
    without_meta = result.model_copy(update={"meta": {}})

    assert "Project brief: Empty State" in without_meta.content[0].text
    assert without_meta.structuredContent["open_tasks"] == []
    assert without_meta.structuredContent["open_blockers"] == []
    assert without_meta.structuredContent["decisions"][0]["title"] == "Only decision recorded"


def test_search_tool_result_shape_groups_mixed_result_kinds(tmp_path: Path) -> None:
    from workstream_mcp.server import SEARCH_OUTPUT_SCHEMA

    db_path = tmp_path / "workstream.db"
    record_session_handoff(
        project="Search Contract",
        source="chatgpt",
        title="Timeline search",
        summary="Portable search result.",
        decisions=[{"title": "Search returns stable IDs", "summary": "Every result exposes kind:id."}],
        tasks=[{"title": "Search task result"}],
        blockers=[{"title": "Search blocker result"}],
        references=[{"label": "Search reference", "uri": "https://example.test/search-contract"}],
        db_path=db_path,
    )
    record_codex_session_summary(
        project="Search Contract",
        title="Search session result",
        summary="Search session summary.",
        tests_run=["pytest"],
        db_path=db_path,
    )

    result = app_tools.search_workstream("Search", project="Search Contract", db_path=db_path)
    kinds = {row["kind"] for row in result.structuredContent["results"]}

    assert result.content
    assert "Search results for 'Search':" in result.content[0].text
    validate(instance=result.structuredContent, schema=SEARCH_OUTPUT_SCHEMA)
    assert {"event", "task", "decision", "blocker", "reference", "codex_session"} <= kinds
    assert all(row["stable_id"] == f"{row['kind']}:{row['id']}" for row in result.structuredContent["results"])
    assert result.meta["defaultView"] == "grouped"
    assert set(result.meta["timelineGroups"]) >= kinds
    assert result.meta["resultsById"]


def test_compose_binds_container_to_localhost_only() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    assert "127.0.0.1:8000:8000" in compose
    assert "WORKSTREAM_PUBLIC_BASE_URL" in compose
    assert "nginx" not in compose.lower()


def test_public_proxy_contract_and_codex_prompt_are_present() -> None:
    contract = Path("docs/public-proxy-contract.md").read_text(encoding="utf-8")
    prompt = Path("examples/nginx-stack-codex-prompt.md").read_text(encoding="utf-8")
    assert "/mcp" in contract
    assert "/sse" in contract
    assert "Authorization" in contract
    assert "Do not modify the `dougal-workstream-mcp` application repository." in prompt
