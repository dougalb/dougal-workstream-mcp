from __future__ import annotations

import contextlib
from typing import Any

from . import app_tools as app_tool_impl
from . import prompts as prompt_templates
from . import resources as resource_renderers
from . import tools as tool_impl
from .auth import JWTTokenVerifier, READ_SCOPE, WRITE_SCOPE, oauth_challenge, protected_resource_metadata
from .auth import reset_current_access_token, set_current_access_token
from .config import WorkstreamConfig, configure_logging, load_config
from .db import WorkstreamDB

PROJECT_BRIEF_WIDGET_URI = "ui://widget/project-brief-v1.html"

OBJECT_OUTPUT_SCHEMA = {"type": "object", "additionalProperties": True}
PROJECTS_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {"projects": {"type": "array", "items": {"type": "object", "additionalProperties": True}}},
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
    "properties": {"results": {"type": "array", "items": {"type": "object", "additionalProperties": True}}},
    "required": ["results"],
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

    return ToolAnnotations(readOnlyHint=read_only, destructiveHint=False, openWorldHint=False)


def _security_schemes(config: WorkstreamConfig, scopes: list[str]) -> list[dict[str, Any]]:
    if config.auth_mode == "oauth":
        return [{"type": "oauth2", "scopes": scopes}]
    return [{"type": "noauth"}]


def _tool_meta(
    config: WorkstreamConfig,
    scopes: list[str],
    output_schema: dict[str, Any] | None = None,
    widget: bool = False,
) -> dict[str, Any]:
    meta: dict[str, Any] = {"securitySchemes": _security_schemes(config, scopes)}
    if output_schema is not None:
        meta["workstream/outputSchema"] = output_schema
    if widget:
        meta["openai/outputTemplate"] = PROJECT_BRIEF_WIDGET_URI
        meta["ui"] = {"resourceUri": PROJECT_BRIEF_WIDGET_URI, "visibility": ["model", "app"]}
    return meta


def _widget_html() -> str:
    return """
<div id="workstream-root">Loading workstream brief...</div>
<style>
  :root { color-scheme: light dark; }
  body { margin: 0; font: 14px/1.45 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
  #workstream-root { padding: 12px; }
  h2 { font-size: 16px; margin: 0 0 8px; }
  ul { margin: 8px 0 0; padding-left: 18px; }
  li { margin: 4px 0; }
</style>
<script type="module">
const root = document.getElementById("workstream-root");
function render(result) {
  const data = result?.structuredContent;
  if (!data?.project) {
    root.textContent = "No project brief available.";
    return;
  }
  const tasks = data.open_tasks ?? [];
  const blockers = data.open_blockers ?? [];
  root.innerHTML = `
    <h2>${data.project.name}</h2>
    <div>${tasks.length} open tasks, ${blockers.length} open blockers</div>
    <ul>${tasks.slice(0, 6).map((task) => `<li>${task.title}</li>`).join("")}</ul>
  `;
}
window.addEventListener("message", (event) => {
  if (event.source !== window.parent) return;
  const message = event.data;
  if (message?.method === "ui/notifications/tool-result") render(message.params);
}, { passive: true });
</script>
""".strip()


def _create_fastmcp_class():
    from mcp.server.fastmcp import FastMCP

    class WorkstreamFastMCP(FastMCP):
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
        instructions="Local-first shared workstream context backed by SQLite.",
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(allowed_hosts=config.allowed_hosts),
    )

    @mcp.tool(annotations=_annotations(False), meta=_tool_meta(config, [READ_SCOPE, WRITE_SCOPE], OBJECT_OUTPUT_SCHEMA))
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

    @mcp.tool(annotations=_annotations(False), meta=_tool_meta(config, [READ_SCOPE, WRITE_SCOPE], OBJECT_OUTPUT_SCHEMA))
    def record_decision(
        project: str,
        title: str,
        summary: str,
        rationale: str,
        sensitivity: str = "internal",
    ) -> dict[str, Any]:
        """Record a project decision."""
        return tool_impl.record_decision(project, title, summary, rationale, sensitivity)

    @mcp.tool(annotations=_annotations(False), meta=_tool_meta(config, [READ_SCOPE, WRITE_SCOPE], OBJECT_OUTPUT_SCHEMA))
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

    @mcp.tool(annotations=_annotations(False), meta=_tool_meta(config, [READ_SCOPE, WRITE_SCOPE], OBJECT_OUTPUT_SCHEMA))
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

    @mcp.tool(annotations=_annotations(False), meta=_tool_meta(config, [READ_SCOPE, WRITE_SCOPE], OBJECT_OUTPUT_SCHEMA))
    def update_task_status(task_id: int, status: str) -> dict[str, Any]:
        """Update a task status to open, blocked, or done."""
        return tool_impl.update_task_status(task_id=task_id, status=status)

    @mcp.tool(annotations=_annotations(False), meta=_tool_meta(config, [READ_SCOPE, WRITE_SCOPE], OBJECT_OUTPUT_SCHEMA))
    def update_blocker_status(blocker_id: int, status: str) -> dict[str, Any]:
        """Update a blocker status to open or resolved."""
        return tool_impl.update_blocker_status(blocker_id=blocker_id, status=status)

    @mcp.tool(annotations=_annotations(True), meta=_tool_meta(config, [READ_SCOPE], SEARCH_OUTPUT_SCHEMA))
    def search_workstream(query: str, project: str | None = None, limit: int = 20):
        """Search captured workstream content."""
        return app_tool_impl.search_workstream(query=query, project=project, limit=limit)

    @mcp.tool(annotations=_annotations(True), meta=_tool_meta(config, [READ_SCOPE], PROJECTS_OUTPUT_SCHEMA))
    def list_projects():
        """List projects in an Apps SDK-safe structured format."""
        return app_tool_impl.list_projects()

    @mcp.tool(annotations=_annotations(True), meta=_tool_meta(config, [READ_SCOPE], TASKS_OUTPUT_SCHEMA))
    def list_open_tasks(project: str | None = None):
        """List open workstream tasks in an Apps SDK-safe structured format."""
        return app_tool_impl.list_open_tasks(project=project)

    @mcp.tool(annotations=_annotations(True), meta=_tool_meta(config, [READ_SCOPE], OBJECT_OUTPUT_SCHEMA, widget=True))
    def get_project_brief(project: str):
        """Return an Apps SDK-safe project brief."""
        return app_tool_impl.get_project_brief(project=project)

    @mcp.resource(
        PROJECT_BRIEF_WIDGET_URI,
        mime_type="text/html;profile=mcp-app",
        meta={
            "ui": {
                "prefersBorder": True,
                "domain": config.public_base_url,
                "csp": {"connectDomains": [config.public_base_url], "resourceDomains": []},
            }
        },
    )
    def project_brief_widget() -> str:
        """Minimal ChatGPT Apps SDK project brief widget."""
        return _widget_html()

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
