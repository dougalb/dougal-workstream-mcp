from __future__ import annotations

from pathlib import Path

from .config import load_config
from .db import WorkstreamDB, today_utc
from .resources import render_project, render_today


def export_markdown(
    db_path: str | Path | None = None,
    export_dir: str | Path | None = None,
) -> dict[str, list[str]]:
    config = load_config()
    database = WorkstreamDB(db_path or config.db_path)
    database.initialize()
    root = Path(export_dir or config.export_dir)
    projects_dir = root / "projects"
    daily_dir = root / "daily"
    projects_dir.mkdir(parents=True, exist_ok=True)
    daily_dir.mkdir(parents=True, exist_ok=True)

    project_files: list[str] = []
    for project in database.list_projects():
        path = projects_dir / f"{project['slug']}.md"
        path.write_text(render_project(project["slug"], db_path=database.path), encoding="utf-8")
        project_files.append(str(path))

    day_path = daily_dir / f"{today_utc()}.md"
    day_path.write_text(render_today(db_path=database.path), encoding="utf-8")

    return {"projects": project_files, "daily": [str(day_path)]}
