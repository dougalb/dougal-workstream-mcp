SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    source TEXT,
    title TEXT NOT NULL,
    summary TEXT,
    sensitivity TEXT NOT NULL DEFAULT 'internal',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS codex_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    event_id INTEGER,
    repo_path TEXT,
    host TEXT,
    goal TEXT NOT NULL,
    status TEXT NOT NULL,
    changed_files_json TEXT NOT NULL DEFAULT '[]',
    commands_run_json TEXT NOT NULL DEFAULT '[]',
    tests_summary TEXT,
    sensitivity TEXT NOT NULL DEFAULT 'internal',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY(event_id) REFERENCES events(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    event_id INTEGER,
    session_id INTEGER,
    title TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    priority TEXT,
    due_date TEXT,
    owner TEXT,
    sensitivity TEXT NOT NULL DEFAULT 'internal',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY(event_id) REFERENCES events(id) ON DELETE SET NULL,
    FOREIGN KEY(session_id) REFERENCES codex_sessions(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    event_id INTEGER,
    session_id INTEGER,
    title TEXT NOT NULL,
    summary TEXT,
    rationale TEXT,
    sensitivity TEXT NOT NULL DEFAULT 'internal',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY(event_id) REFERENCES events(id) ON DELETE SET NULL,
    FOREIGN KEY(session_id) REFERENCES codex_sessions(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS blockers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    event_id INTEGER,
    session_id INTEGER,
    title TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    owner TEXT,
    sensitivity TEXT NOT NULL DEFAULT 'internal',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY(event_id) REFERENCES events(id) ON DELETE SET NULL,
    FOREIGN KEY(session_id) REFERENCES codex_sessions(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS "references" (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    event_id INTEGER,
    session_id INTEGER,
    label TEXT,
    uri TEXT NOT NULL,
    description TEXT,
    sensitivity TEXT NOT NULL DEFAULT 'internal',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY(event_id) REFERENCES events(id) ON DELETE SET NULL,
    FOREIGN KEY(session_id) REFERENCES codex_sessions(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_events_project_created ON events(project_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tasks_project_status ON tasks(project_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_decisions_project_created ON decisions(project_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_blockers_project_status ON blockers(project_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_references_project_created ON "references"(project_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_codex_sessions_project_created ON codex_sessions(project_id, created_at DESC);
"""
