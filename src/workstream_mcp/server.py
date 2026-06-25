from __future__ import annotations

import contextlib
from typing import Any

from . import __version__
from . import app_tools as app_tool_impl
from . import prompts as prompt_templates
from . import resources as resource_renderers
from . import tools as tool_impl
from . import ui_resources
from .auth import JWTTokenVerifier, READ_SCOPE, WRITE_SCOPE, oauth_challenge, protected_resource_metadata
from .auth import reset_current_access_token, set_current_access_token
from .config import WorkstreamConfig, configure_logging, load_config
from .db import WorkstreamDB

PROJECT_BRIEF_UI_URI = "ui://workstreams/project-brief.html"
SEARCH_RESULTS_UI_URI = "ui://workstreams/search-results.html"
WRITE_REVIEW_UI_URI = "ui://workstreams/write-review.html"
LEGACY_PROJECT_BRIEF_WIDGET_URI = "ui://widget/project-brief-v1.html"

OBJECT_OUTPUT_SCHEMA = {"type": "object", "additionalProperties": True}
CONFIRMATION_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "project_id": {"type": "integer"},
        "project_slug": {"type": "string"},
        "event_id": {"type": ["integer", "null"]},
        "created_event_ids": {"type": "array", "items": {"type": "integer"}},
        "summary": {"type": "string"},
        "created": {"type": "boolean"},
    },
    "additionalProperties": True,
}
PROJECTS_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "projects": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "slug": {"type": "string"},
                    "name": {"type": "string"},
                    "open_tasks": {"type": "integer"},
                    "open_blockers": {"type": "integer"},
                    "last_event_at": {"type": ["string", "null"]},
                },
                "required": ["id", "slug", "name"],
                "additionalProperties": True,
            },
        }
    },
    "required": ["projects"],
    "additionalProperties": True,
}
TASKS_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {"tasks": {"type": "array", "items": {"type": "object", "additionalProperties": True}}},
    "required": ["tasks"],
    "additionalProperties": True,
}
SEARCH_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string"},
        "project": {"type": ["string", "null"]},
        "count": {"type": "integer"},
        "omitted_sensitive_rows": {"type": "integer"},
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string"},
                    "id": {"type": "integer"},
                    "stable_id": {"type": "string"},
                    "project": {"type": "string"},
                    "title": {"type": "string"},
                    "snippet": {"type": ["string", "null"]},
                    "created_at": {"type": ["string", "null"]},
                },
                "required": ["kind", "id", "stable_id", "project", "title"],
                "additionalProperties": True,
            },
        },
    },
    "required": ["query", "count", "results"],
    "additionalProperties": True,
}
EVENTS_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {"events": {"type": "array", "items": {"type": "object", "additionalProperties": True}}},
    "required": ["events"],
    "additionalProperties": True,
}
DIGEST_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "unconsumed_events": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
        "assigned_open_tasks": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
        "open_blockers": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
    },
    "required": ["unconsumed_events", "assigned_open_tasks", "open_blockers"],
    "additionalProperties": True,
}
PROJECT_BRIEF_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "project": {
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "slug": {"type": "string"},
                "name": {"type": "string"},
            },
            "required": ["id", "slug", "name"],
            "additionalProperties": True,
        },
        "project_brief": {"type": ["object", "null"], "additionalProperties": True},
        "recent_events": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
        "open_tasks": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
        "decisions": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
        "open_blockers": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
        "references": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
        "codex_sessions": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
        "omitted_sensitive_rows": {"type": "integer"},
        "error": {"type": "string"},
    },
    "additionalProperties": True,
}


class WorkstreamOAuthMiddleware:
    def __init__(self, app, config: WorkstreamConfig):
        self.app = app
        self.config = config
        self.verifier = JWTTokenVerifier(config) if config.auth_mode == "oauth" else None

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or self.verifier is None or not self._protected(scope.get("path", "")):
            await self.app(scope, receive, send)
            return

        from starlette.responses import JSONResponse

        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        authorization = headers.get(b"authorization", b"").decode("utf-8")
        token = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
        access_token = await self.verifier.verify_token(token) if token else None
        if access_token is None or READ_SCOPE not in set(access_token.scopes):
            challenge = oauth_challenge(self.config)
            response = JSONResponse(
                {"error": "unauthorized", "detail": "OAuth bearer token with workstream.read scope is required."},
                status_code=401,
                headers={"WWW-Authenticate": challenge.header_value()},
            )
            await response(scope, receive, send)
            return

        token_context = set_current_access_token(access_token)
        try:
            await self.app(scope, receive, send)
        finally:
            reset_current_access_token(token_context)

    @staticmethod
    def _protected(path: str) -> bool:
        return path == "/mcp" or path == "/sse" or path.startswith("/messages")


def _annotations(read_only: bool):
    from mcp.types import ToolAnnotations

    return ToolAnnotations(readOnlyHint=read_only, destructiveHint=False, idempotentHint=False, openWorldHint=False)


def _security_schemes(config: WorkstreamConfig, scopes: list[str]) -> list[dict[str, Any]]:
    if config.auth_mode == "oauth":
        return [{"type": "oauth2", "scopes": scopes}]
    return [{"type": "noauth"}]


def _tool_meta(
    config: WorkstreamConfig,
    scopes: list[str],
    output_schema: dict[str, Any] | None = None,
    ui_resource_uri: str | None = None,
    invoking: str | None = None,
    invoked: str | None = None,
) -> dict[str, Any]:
    meta: dict[str, Any] = {"securitySchemes": _security_schemes(config, scopes)}
    if output_schema is not None:
        meta["workstream/outputSchema"] = output_schema
    if ui_resource_uri:
        # Prefer standard MCP Apps metadata, then add OpenAI aliases for ChatGPT compatibility.
        meta["ui"] = {"resourceUri": ui_resource_uri}
        meta["openai/outputTemplate"] = ui_resource_uri
    if invoking:
        meta["openai/toolInvocation/invoking"] = invoking
    if invoked:
        meta["openai/toolInvocation/invoked"] = invoked
    return meta


def _ui_resource_meta(description: str) -> dict[str, Any]:
    csp = {"connectDomains": [], "resourceDomains": []}
    return {
        "ui": {"prefersBorder": True, "csp": csp},
        "openai/widgetDescription": description,
        "openai/widgetPrefersBorder": True,
        "openai/widgetCSP": {"connect_domains": [], "resource_domains": []},
    }


def _create_fastmcp_class():
    from mcp.server.fastmcp import FastMCP

    class WorkstreamFastMCP(FastMCP):
        def __init__(self, *args: Any, server_version: str | None = None, **kwargs: Any):
            super().__init__(*args, **kwargs)
            if server_version is not None:
                self._mcp_server.version = server_version

        async def list_tools(self):
            tools = await super().list_tools()
            for tool in tools:
                meta = dict(tool.meta or {})
                output_schema = meta.pop("workstream/outputSchema", None)
                if output_schema is not None:
                    tool.outputSchema = output_schema
                if meta.get("securitySchemes"):
                    tool.securitySchemes = meta["securitySchemes"]
                tool.meta = meta or None
            return tools

    return WorkstreamFastMCP


def create_mcp(config: WorkstreamConfig | None = None):
    from mcp.server.transport_security import TransportSecuritySettings

    config = config or load_config()
    FastMCP = _create_fastmcp_class()

    mcp = FastMCP(
        "dougal-workstream-mcp",
        server_version=__version__,
        instructions="Local-first shared workstream context backed by SQLite.",
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(allowed_hosts=config.allowed_hosts),
    )

    @mcp.tool(
        annotations=_annotations(False),
        meta=_tool_meta(
            config,
            [READ_SCOPE, WRITE_SCOPE],
            CONFIRMATION_OUTPUT_SCHEMA,
            ui_resource_uri=WRITE_REVIEW_UI_URI,
            invoking="Recording handoff...",
            invoked="Handoff recorded",
        ),
    )
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
    ) -> dict[str, Any]:
        """Capture a structured handoff from an assistant or tool."""
        return tool_impl.capture_handoff(
            source=source,
            project=project,
            title=title,
            summary=summary,
            decisions=decisions,
            next_actions=next_actions,
            blockers=blockers,
            references=references,
            sensitivity=sensitivity,
        )

    @mcp.tool(
        annotations=_annotations(False),
        meta=_tool_meta(
            config,
            [READ_SCOPE, WRITE_SCOPE],
            CONFIRMATION_OUTPUT_SCHEMA,
            ui_resource_uri=WRITE_REVIEW_UI_URI,
            invoking="Recording handoff...",
            invoked="Handoff recorded",
        ),
    )
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
    ) -> dict[str, Any]:
        """Record a durable cross-agent session handoff without storing a full chat transcript."""
        return tool_impl.record_session_handoff(
            project=project,
            source=source,
            title=title,
            summary=summary,
            decisions=decisions,
            tasks=tasks,
            blockers=blockers,
            references=references,
            next_actions=next_actions,
            open_questions=open_questions,
            sensitivity=sensitivity,
            source_agent=source_agent,
        )

    @mcp.tool(
        annotations=_annotations(False),
        meta=_tool_meta(
            config,
            [READ_SCOPE, WRITE_SCOPE],
            CONFIRMATION_OUTPUT_SCHEMA,
            ui_resource_uri=WRITE_REVIEW_UI_URI,
            invoking="Recording decision...",
            invoked="Decision recorded",
        ),
    )
    def record_decision(
        project: str,
        title: str,
        summary: str,
        rationale: str,
        sensitivity: str = "internal",
    ) -> dict[str, Any]:
        """Record a project decision."""
        return tool_impl.record_decision(project, title, summary, rationale, sensitivity)

    @mcp.tool(
        annotations=_annotations(False),
        meta=_tool_meta(
            config,
            [READ_SCOPE, WRITE_SCOPE],
            CONFIRMATION_OUTPUT_SCHEMA,
            ui_resource_uri=WRITE_REVIEW_UI_URI,
            invoking="Recording decision...",
            invoked="Decision recorded",
        ),
    )
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
    ) -> dict[str, Any]:
        """Record a durable decision made in a ChatGPT planning or design session."""
        return tool_impl.record_chatgpt_decision(
            project=project,
            title=title,
            summary=summary,
            rationale=rationale,
            alternatives_considered=alternatives_considered,
            implications=implications,
            sensitivity=sensitivity,
            supersedes_event_id=supersedes_event_id,
            source_agent=source_agent,
        )

    @mcp.tool(
        annotations=_annotations(False),
        meta=_tool_meta(
            config,
            [READ_SCOPE, WRITE_SCOPE],
            CONFIRMATION_OUTPUT_SCHEMA,
            ui_resource_uri=WRITE_REVIEW_UI_URI,
            invoking="Recording task...",
            invoked="Task recorded",
        ),
    )
    def record_task(
        project: str,
        title: str,
        description: str = "",
        priority: str | None = None,
        due_date: str | None = None,
        owner: str | None = None,
        sensitivity: str = "internal",
    ) -> dict[str, Any]:
        """Record an open task."""
        return tool_impl.record_task(project, title, description, priority, due_date, owner, sensitivity)

    @mcp.tool(
        annotations=_annotations(False),
        meta=_tool_meta(
            config,
            [READ_SCOPE, WRITE_SCOPE],
            CONFIRMATION_OUTPUT_SCHEMA,
            ui_resource_uri=WRITE_REVIEW_UI_URI,
            invoking="Recording follow-up...",
            invoked="Follow-up recorded",
        ),
    )
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
    ) -> dict[str, Any]:
        """Create a structured follow-up task intended for OpenClaw or a named OpenClaw agent."""
        return tool_impl.record_openclaw_followup(
            project=project,
            title=title,
            description=description,
            priority=priority,
            due_date=due_date,
            assigned_agent=assigned_agent,
            context=context,
            references=references,
            sensitivity=sensitivity,
        )

    @mcp.tool(
        annotations=_annotations(False),
        meta=_tool_meta(
            config,
            [READ_SCOPE, WRITE_SCOPE],
            CONFIRMATION_OUTPUT_SCHEMA,
            ui_resource_uri=WRITE_REVIEW_UI_URI,
            invoking="Recording session...",
            invoked="Session recorded",
        ),
    )
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
    ) -> dict[str, Any]:
        """Record an end-of-session Codex summary."""
        return tool_impl.record_codex_session(
            project=project,
            repo_path=repo_path,
            host=host,
            goal=goal,
            status=status,
            changed_files=changed_files,
            commands_run=commands_run,
            tests_summary=tests_summary,
            decisions=decisions,
            next_actions=next_actions,
            blockers=blockers,
            sensitivity=sensitivity,
        )

    @mcp.tool(
        annotations=_annotations(False),
        meta=_tool_meta(
            config,
            [READ_SCOPE, WRITE_SCOPE],
            CONFIRMATION_OUTPUT_SCHEMA,
            ui_resource_uri=WRITE_REVIEW_UI_URI,
            invoking="Recording session summary...",
            invoked="Session summary recorded",
        ),
    )
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
    ) -> dict[str, Any]:
        """Record what Codex implemented, changed, tested, and left for follow-up."""
        return tool_impl.record_codex_session_summary(
            project=project,
            title=title,
            summary=summary,
            files_changed=files_changed,
            commands_run=commands_run,
            tests_run=tests_run,
            implementation_notes=implementation_notes,
            decisions=decisions,
            tasks_created=tasks_created,
            blockers=blockers,
            followups=followups,
            references=references,
            sensitivity=sensitivity,
            source_agent=source_agent,
        )

    @mcp.tool(annotations=_annotations(False), meta=_tool_meta(config, [READ_SCOPE, WRITE_SCOPE], CONFIRMATION_OUTPUT_SCHEMA))
    def update_task_status(task_id: int, status: str) -> dict[str, Any]:
        """Update a task status to open, blocked, or done."""
        return tool_impl.update_task_status(task_id=task_id, status=status)

    @mcp.tool(annotations=_annotations(False), meta=_tool_meta(config, [READ_SCOPE, WRITE_SCOPE], CONFIRMATION_OUTPUT_SCHEMA))
    def update_blocker_status(blocker_id: int, status: str) -> dict[str, Any]:
        """Update a blocker status to open or resolved."""
        return tool_impl.update_blocker_status(blocker_id=blocker_id, status=status)

    @mcp.tool(annotations=_annotations(False), meta=_tool_meta(config, [READ_SCOPE, WRITE_SCOPE], CONFIRMATION_OUTPUT_SCHEMA))
    def mark_event_consumed_by_agent(
        consumer_agent: str,
        event_ids: list[int] | None = None,
        event_id: int | None = None,
        project: str | None = None,
        notes: str | None = None,
        action_taken: str | None = None,
    ) -> dict[str, Any]:
        """Mark one or more semantic workstream events consumed by an agent and advance its cursor."""
        return tool_impl.mark_event_consumed_by_agent(
            consumer_agent=consumer_agent,
            event_ids=event_ids,
            event_id=event_id,
            project=project,
            notes=notes,
            action_taken=action_taken,
        )

    @mcp.tool(
        annotations=_annotations(False),
        meta=_tool_meta(
            config,
            [READ_SCOPE, WRITE_SCOPE],
            CONFIRMATION_OUTPUT_SCHEMA,
            ui_resource_uri=WRITE_REVIEW_UI_URI,
            invoking="Updating project brief...",
            invoked="Project brief updated",
        ),
    )
    def create_or_update_project_brief(
        project: str,
        summary_delta: str,
        status: str | None = None,
        current_state: str | None = None,
        next_steps: list[Any] | None = None,
        risks: list[Any] | None = None,
        source_event_ids: list[int] | None = None,
        sensitivity: str = "internal",
    ) -> dict[str, Any]:
        """Append durable project-brief context derived from structured Workstream events."""
        return tool_impl.create_or_update_project_brief(
            project=project,
            summary_delta=summary_delta,
            status=status,
            current_state=current_state,
            next_steps=next_steps,
            risks=risks,
            source_event_ids=source_event_ids,
            sensitivity=sensitivity,
        )

    @mcp.tool(
        annotations=_annotations(True),
        meta=_tool_meta(
            config,
            [READ_SCOPE],
            SEARCH_OUTPUT_SCHEMA,
            ui_resource_uri=SEARCH_RESULTS_UI_URI,
            invoking="Searching workstreams...",
            invoked="Search results ready",
        ),
    )
    def search_workstream(query: str, project: str | None = None, limit: int = 20):
        """Search captured workstream content."""
        return app_tool_impl.search_workstream(query=query, project=project, limit=limit)

    @mcp.tool(annotations=_annotations(True), meta=_tool_meta(config, [READ_SCOPE], EVENTS_OUTPUT_SCHEMA))
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
    ):
        """List semantic Workstream events since a checkpoint, optionally excluding events consumed by an agent."""
        return app_tool_impl.list_recent_changes_since(
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

    @mcp.tool(annotations=_annotations(True), meta=_tool_meta(config, [READ_SCOPE], DIGEST_OUTPUT_SCHEMA))
    def get_agent_digest(
        agent: str,
        project: str | None = None,
        include_tasks: bool = True,
        include_blockers: bool = True,
        include_recent_decisions: bool = True,
        include_unconsumed_events: bool = True,
        limit: int = 20,
    ):
        """Return a compact startup digest of unconsumed events and open work for an agent."""
        return app_tool_impl.get_agent_digest(
            agent=agent,
            project=project,
            include_tasks=include_tasks,
            include_blockers=include_blockers,
            include_recent_decisions=include_recent_decisions,
            include_unconsumed_events=include_unconsumed_events,
            limit=limit,
        )

    @mcp.tool(annotations=_annotations(True), meta=_tool_meta(config, [READ_SCOPE], PROJECTS_OUTPUT_SCHEMA))
    def list_projects():
        """List projects in an Apps SDK-safe structured format."""
        return app_tool_impl.list_projects()

    @mcp.tool(annotations=_annotations(True), meta=_tool_meta(config, [READ_SCOPE], TASKS_OUTPUT_SCHEMA))
    def list_open_tasks(project: str | None = None):
        """List open workstream tasks in an Apps SDK-safe structured format."""
        return app_tool_impl.list_open_tasks(project=project)

    @mcp.tool(
        annotations=_annotations(True),
        meta=_tool_meta(
            config,
            [READ_SCOPE],
            PROJECT_BRIEF_OUTPUT_SCHEMA,
            ui_resource_uri=PROJECT_BRIEF_UI_URI,
            invoking="Loading project brief...",
            invoked="Project brief ready",
        ),
    )
    def get_project_brief(project: str):
        """Return an Apps SDK-safe project brief."""
        return app_tool_impl.get_project_brief(project=project)

    @mcp.resource(
        PROJECT_BRIEF_UI_URI,
        mime_type="text/html;profile=mcp-app",
        meta=_ui_resource_meta(
            "Shows a Workstream project brief with recent decisions, open tasks, blockers, references, and session summaries."
        ),
    )
    def project_brief_ui() -> str:
        """MCP Apps project brief UI resource."""
        return ui_resources.project_brief_html()

    @mcp.resource(
        SEARCH_RESULTS_UI_URI,
        mime_type="text/html;profile=mcp-app",
        meta=_ui_resource_meta("Shows grouped Workstream search results with stable IDs, snippets, projects, and timestamps."),
    )
    def search_results_ui() -> str:
        """MCP Apps search and timeline UI resource."""
        return ui_resources.search_results_html()

    @mcp.resource(
        WRITE_REVIEW_UI_URI,
        mime_type="text/html;profile=mcp-app",
        meta=_ui_resource_meta("Shows a review of a semantic Workstream write after an explicit tool invocation."),
    )
    def write_review_ui() -> str:
        """MCP Apps write review UI resource."""
        return ui_resources.write_review_html()

    @mcp.resource(
        LEGACY_PROJECT_BRIEF_WIDGET_URI,
        mime_type="text/html;profile=mcp-app",
        meta=_ui_resource_meta("Legacy alias for the Workstream project brief UI resource."),
    )
    def legacy_project_brief_widget() -> str:
        """Compatibility alias for the original project brief widget URI."""
        return ui_resources.project_brief_html()

    @mcp.resource("workstream://today", mime_type="text/markdown")
    def today() -> str:
        """Read today's captured workstream events."""
        return resource_renderers.render_today()

    @mcp.resource("workstream://projects", mime_type="text/markdown")
    def projects() -> str:
        """List workstream projects."""
        return resource_renderers.render_projects()

    @mcp.resource("workstream://projects/{project_id}", mime_type="text/markdown")
    def project(project_id: str) -> str:
        """Read a project brief."""
        return resource_renderers.render_project(project_id)

    @mcp.resource("workstream://recent", mime_type="text/markdown")
    def recent() -> str:
        """Read recent workstream events."""
        return resource_renderers.render_recent()

    @mcp.resource("workstream://tasks/open", mime_type="text/markdown")
    def open_tasks() -> str:
        """Read all open tasks."""
        return resource_renderers.render_open_tasks()

    @mcp.resource("workstream://projects/{project_id}/decisions", mime_type="text/markdown")
    def project_decisions(project_id: str) -> str:
        """Read decisions for a project."""
        return resource_renderers.render_project_decisions(project_id)

    @mcp.resource("workstream://projects/{project_id}/tasks", mime_type="text/markdown")
    def project_tasks(project_id: str) -> str:
        """Read open tasks for a project."""
        return resource_renderers.render_project_tasks(project_id)

    @mcp.resource("workstream://projects/{project_id}/blockers", mime_type="text/markdown")
    def project_blockers(project_id: str) -> str:
        """Read open blockers for a project."""
        return resource_renderers.render_project_blockers(project_id)

    @mcp.prompt()
    def chatgpt_handoff(project: str = "", sensitivity: str = "internal") -> str:
        """Template for ChatGPT to create a structured handoff."""
        return prompt_templates.chatgpt_handoff(project=project, sensitivity=sensitivity)

    @mcp.prompt()
    def codex_session_summary(project: str = "", repo_path: str = "", host: str = "") -> str:
        """Template for Codex to summarize an implementation session."""
        return prompt_templates.codex_session_summary(project=project, repo_path=repo_path, host=host)

    @mcp.prompt()
    def project_brief(project: str) -> str:
        """Template that includes current project state."""
        return prompt_templates.project_brief(project=project)

    return mcp


def create_http_app(config: WorkstreamConfig | None = None):
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route
    from starlette.middleware import Middleware

    config = config or load_config()
    mcp = create_mcp(config)
    streamable_app = mcp.streamable_http_app()
    sse_app = mcp.sse_app()

    async def healthz(_request):
        database = WorkstreamDB(config.db_path)
        return JSONResponse(database.health())

    async def readyz(_request):
        database = WorkstreamDB(config.db_path)
        return JSONResponse(database.health())

    async def oauth_resource_metadata(_request):
        return JSONResponse(protected_resource_metadata(config))

    @contextlib.asynccontextmanager
    async def lifespan(_app: Starlette):
        async with mcp.session_manager.run():
            yield

    return Starlette(
        routes=[
            Route("/healthz", healthz, methods=["GET"]),
            Route("/readyz", readyz, methods=["GET"]),
            Route("/.well-known/oauth-protected-resource", oauth_resource_metadata, methods=["GET"]),
            *streamable_app.routes,
            *sse_app.routes,
        ],
        middleware=[Middleware(WorkstreamOAuthMiddleware, config=config)],
        lifespan=lifespan,
    )


def run_stdio() -> None:
    config = load_config()
    configure_logging(config)
    WorkstreamDB(config.db_path).initialize()
    create_mcp(config).run(transport="stdio")


def run_http(host: str = "127.0.0.1", port: int = 8000) -> None:
    config = load_config()
    configure_logging(config)
    WorkstreamDB(config.db_path).initialize()
    import uvicorn

    uvicorn.run(
        create_http_app(config),
        host=host,
        port=port,
        proxy_headers=config.trust_proxy_headers,
        forwarded_allow_ips="*" if config.trust_proxy_headers else None,
    )


def main() -> None:
    run_stdio()


if __name__ == "__main__":
    main()
