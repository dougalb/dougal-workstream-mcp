from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.utils import base64url_encode
from starlette.testclient import TestClient

from workstream_mcp import app_tools
from workstream_mcp.auth import READ_SCOPE, SENSITIVE_SCOPE, WRITE_SCOPE, JWTTokenVerifier, set_current_access_token
from workstream_mcp.config import WorkstreamConfig
from workstream_mcp.cli import _load_capture_file, main
from workstream_mcp.db import WorkstreamDB
from workstream_mcp.export import export_markdown
from workstream_mcp.resources import render_open_tasks, render_project_brief, render_projects
from workstream_mcp.safety import SecretDetectedError, assert_safe_to_store
from workstream_mcp.tools import capture_handoff, record_codex_session, search_workstream, update_blocker_status, update_task_status


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
    from workstream_mcp.server import create_mcp

    config, _key = _oauth_config(tmp_path)
    tools = {tool.name: tool for tool in asyncio.run(create_mcp(config).list_tools())}

    brief = tools["get_project_brief"]
    assert brief.securitySchemes == [{"type": "oauth2", "scopes": [READ_SCOPE]}]
    assert brief.meta["securitySchemes"] == brief.securitySchemes
    assert brief.meta["openai/outputTemplate"] == "ui://widget/project-brief-v1.html"
    assert brief.outputSchema["type"] == "object"
    assert brief.annotations.readOnlyHint is True

    capture = tools["capture_handoff"]
    assert capture.securitySchemes == [{"type": "oauth2", "scopes": [READ_SCOPE, WRITE_SCOPE]}]
    assert capture.outputSchema["type"] == "object"
    assert capture.annotations.readOnlyHint is False
    assert capture.annotations.openWorldHint is False
    assert capture.annotations.destructiveHint is False


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
