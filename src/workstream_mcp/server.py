from __future__ import annotations

import contextlib
from typing import Any

from . import prompts as prompt_templates
from . import resources as resource_renderers
from . import tools as tool_impl
from .config import configure_logging
from .db import WorkstreamDB


def create_mcp():
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP(
        "dougal-workstream-mcp",
        instructions="Local-first shared workstream context backed by SQLite.",
        stateless_http=True,
        json_response=True,
    )

    @mcp.tool()
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

    @mcp.tool()
    def record_decision(
        project: str,
        title: str,
        summary: str,
        rationale: str,
        sensitivity: str = "internal",
    ) -> dict[str, Any]:
        """Record a project decision."""
        return tool_impl.record_decision(project, title, summary, rationale, sensitivity)

    @mcp.tool()
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

    @mcp.tool()
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

    @mcp.tool()
    def update_task_status(task_id: int, status: str) -> dict[str, Any]:
        """Update a task status to open, blocked, or done."""
        return tool_impl.update_task_status(task_id=task_id, status=status)

    @mcp.tool()
    def update_blocker_status(blocker_id: int, status: str) -> dict[str, Any]:
        """Update a blocker status to open or resolved."""
        return tool_impl.update_blocker_status(blocker_id=blocker_id, status=status)

    @mcp.tool()
    def search_workstream(query: str, project: str | None = None, limit: int = 20) -> dict[str, Any]:
        """Search captured workstream content."""
        return tool_impl.search_workstream(query=query, project=project, limit=limit)

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


def create_http_app():
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Mount, Route

    mcp = create_mcp()

    async def healthz(_request):
        database = WorkstreamDB()
        return JSONResponse(database.health())

    async def readyz(_request):
        database = WorkstreamDB()
        return JSONResponse(database.health())

    @contextlib.asynccontextmanager
    async def lifespan(_app: Starlette):
        async with mcp.session_manager.run():
            yield

    return Starlette(
        routes=[
            Route("/healthz", healthz, methods=["GET"]),
            Route("/readyz", readyz, methods=["GET"]),
            Mount("/", app=mcp.streamable_http_app()),
        ],
        lifespan=lifespan,
    )


def run_stdio() -> None:
    configure_logging()
    WorkstreamDB().initialize()
    create_mcp().run(transport="stdio")


def run_http(host: str = "0.0.0.0", port: int = 8000) -> None:
    configure_logging()
    WorkstreamDB().initialize()
    import uvicorn

    uvicorn.run(create_http_app(), host=host, port=port)


def main() -> None:
    run_stdio()


if __name__ == "__main__":
    main()
