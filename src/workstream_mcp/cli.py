from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from .config import load_config
from .db import WorkstreamDB
from .export import export_markdown
from .resources import render_open_tasks, render_projects, render_recent
from .tools import capture_handoff


SECTION_ALIASES = {
    "source": "source",
    "project": "project",
    "title": "title",
    "summary": "summary",
    "decisions": "decisions",
    "decision": "decisions",
    "next actions": "next_actions",
    "next action": "next_actions",
    "next_actions": "next_actions",
    "actions": "next_actions",
    "tasks": "next_actions",
    "blockers": "blockers",
    "blocker": "blockers",
    "references": "references",
    "reference": "references",
    "sensitivity": "sensitivity",
}
LABEL_RE = re.compile(r"^([A-Za-z][A-Za-z _-]{1,40}):\s*(.*)$")


def _section_key(label: str) -> str | None:
    normalized = label.strip().lower().replace("_", " ").replace("-", " ")
    return SECTION_ALIASES.get(normalized)


def _parse_markdown_handoff(text: str, source: str | None, project: str | None, file_path: Path) -> dict[str, Any]:
    sections: dict[str, list[str]] = {key: [] for key in set(SECTION_ALIASES.values())}
    current = "summary"
    title = file_path.stem.replace("-", " ").title()

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            sections.setdefault(current, []).append("")
            continue

        if stripped.startswith("#"):
            heading = stripped.lstrip("#").strip()
            key = _section_key(heading)
            current = key or current
            if stripped.startswith("# ") and key is None:
                title = heading
            continue

        label_match = LABEL_RE.match(stripped)
        if label_match:
            key = _section_key(label_match.group(1))
            if key:
                current = key
                rest = label_match.group(2).strip()
                if rest:
                    sections.setdefault(current, []).append(rest)
                continue

        sections.setdefault(current, []).append(line)

    def text_section(*names: str) -> str:
        for name in names:
            value = "\n".join(sections.get(name, [])).strip()
            if value:
                return value
        return ""

    def list_section(*names: str) -> list[str]:
        items: list[str] = []
        for name in names:
            pending_lines: list[str] = []
            for line in sections.get(name, []):
                stripped = line.strip()
                if stripped.startswith(("-", "*")):
                    if pending_lines:
                        items.append("\n".join(pending_lines).strip())
                        pending_lines = []
                    item = stripped[1:].strip()
                    if item:
                        pending_lines.append(item)
                elif stripped and pending_lines:
                    pending_lines.append(stripped)
            if pending_lines:
                items.append("\n".join(pending_lines).strip())
        return items

    return {
        "source": source or text_section("source") or "unknown",
        "project": project or text_section("project") or "default",
        "title": text_section("title") or title,
        "summary": text_section("summary"),
        "decisions": list_section("decisions"),
        "next_actions": list_section("next_actions"),
        "blockers": list_section("blockers"),
        "references": list_section("references"),
        "sensitivity": text_section("sensitivity") or "internal",
    }


def _load_capture_file(path: Path, source: str | None, project: str | None) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        data = json.loads(text)
    else:
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = _parse_markdown_handoff(text, source=source, project=project, file_path=path)

    if source:
        data["source"] = source
    if project:
        data["project"] = project
    return data


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="workstream", description="Local workstream MCP server")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="Initialize the local SQLite database")

    capture = sub.add_parser("capture", help="Capture a handoff from JSON or structured Markdown")
    capture.add_argument("--file", required=True, type=Path)
    capture.add_argument("--source")
    capture.add_argument("--project")

    sub.add_parser("list-projects", help="List projects")
    sub.add_parser("list-tasks", help="List open tasks")
    sub.add_parser("recent", help="Show recent events")
    sub.add_parser("export-markdown", help="Export readable Markdown files")

    serve = sub.add_parser("serve", help="Run the MCP server")
    serve.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", type=int, default=8000)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config()
    database = WorkstreamDB(config.db_path)

    try:
        if args.command == "init":
            database.initialize()
            print(f"Initialized workstream database at {database.path}")
            return 0
        if args.command == "capture":
            data = _load_capture_file(args.file, source=args.source, project=args.project)
            result = capture_handoff(**data, db_path=database.path)
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0
        if args.command == "list-projects":
            print(render_projects(db_path=database.path))
            return 0
        if args.command == "list-tasks":
            print(render_open_tasks(db_path=database.path))
            return 0
        if args.command == "recent":
            print(render_recent(db_path=database.path))
            return 0
        if args.command == "export-markdown":
            result = export_markdown(db_path=database.path, export_dir=config.export_dir)
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0
        if args.command == "serve":
            from .server import run_http, run_stdio

            if args.transport == "stdio":
                run_stdio()
            else:
                run_http(host=args.host, port=args.port)
            return 0
    except Exception as exc:
        print(f"workstream: error: {exc}", file=sys.stderr)
        return 1

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
