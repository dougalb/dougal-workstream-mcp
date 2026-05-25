from __future__ import annotations

from pathlib import Path

from .resources import render_project


def chatgpt_handoff(project: str = "", sensitivity: str = "internal") -> str:
    return f"""Create a workstream handoff using this structure.

Project: {project}
Sensitivity: {sensitivity}

Title:

Summary:

Decisions:
- 

Next Actions:
- 

Blockers:
- 

References:
- 

Rules:
- Do not include secrets, API keys, passwords, tokens, private keys, or OAuth secrets.
- Store references to secrets only, such as op://..., 1password://..., or vault://....
"""


def codex_session_summary(project: str = "", repo_path: str = "", host: str = "") -> str:
    return f"""Fill out this Codex end-of-session summary for the workstream.

Project: {project}
Repo Path: {repo_path}
Host: {host}

Goal:

Status:

Changed Files:
- 

Commands Run:
- 

Tests Summary:

Decisions:
- 

Next Actions:
- 

Blockers:
- 

Sensitivity: internal

Rules:
- Do not include secrets, API keys, passwords, tokens, private keys, or OAuth secrets.
- Store references to secrets only, such as op://..., 1password://..., or vault://....
"""


def project_brief(project: str, db_path: str | Path | None = None) -> str:
    current_state = render_project(project, db_path=db_path)
    return f"""Use the current workstream state below to brief the project clearly.

Focus on current goal, recent decisions, open tasks, blockers, and what should happen next.

{current_state}
"""
