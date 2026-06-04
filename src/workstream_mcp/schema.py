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
    source_agent TEXT,
    title TEXT NOT NULL,
    summary TEXT,
    body TEXT,
    rationale TEXT,
    next_actions_json TEXT NOT NULL DEFAULT '[]',
    references_json TEXT NOT NULL DEFAULT '[]',
    sensitivity TEXT NOT NULL DEFAULT 'internal',
    supersedes_event_id INTEGER,
    related_task_id INTEGER,
    related_decision_id INTEGER,
    related_blocker_id INTEGER,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY(supersedes_event_id) REFERENCES events(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS event_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    event_id INTEGER NOT NULL,
    linked_kind TEXT NOT NULL,
    linked_id INTEGER NOT NULL,
    relationship TEXT NOT NULL DEFAULT 'related',
    created_at TEXT NOT NULL,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY(event_id) REFERENCES events(id) ON DELETE CASCADE
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

CREATE TABLE IF NOT EXISTS agent_event_consumption (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL,
    consumer_agent TEXT NOT NULL,
    consumed_at TEXT NOT NULL,
    action_taken TEXT,
    notes TEXT,
    FOREIGN KEY(event_id) REFERENCES events(id) ON DELETE CASCADE,
    UNIQUE(event_id, consumer_agent)
);

CREATE TABLE IF NOT EXISTS agent_project_cursors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    consumer_agent TEXT NOT NULL,
    last_event_id INTEGER NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY(last_event_id) REFERENCES events(id) ON DELETE CASCADE,
    UNIQUE(project_id, consumer_agent)
);

CREATE TABLE IF NOT EXISTS project_briefs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL UNIQUE,
    summary TEXT NOT NULL DEFAULT '',
    status TEXT,
    current_state TEXT,
    next_steps_json TEXT NOT NULL DEFAULT '[]',
    risks_json TEXT NOT NULL DEFAULT '[]',
    source_event_ids_json TEXT NOT NULL DEFAULT '[]',
    sensitivity TEXT NOT NULL DEFAULT 'internal',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_events_project_created ON events(project_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_project_type_created ON events(project_id, event_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_source_created ON events(source, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_event_links_event ON event_links(event_id, linked_kind, linked_id);
CREATE INDEX IF NOT EXISTS idx_tasks_project_status ON tasks(project_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_decisions_project_created ON decisions(project_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_blockers_project_status ON blockers(project_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_references_project_created ON "references"(project_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_codex_sessions_project_created ON codex_sessions(project_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_consumption_agent_event ON agent_event_consumption(consumer_agent, event_id);
CREATE INDEX IF NOT EXISTS idx_cursors_agent_project ON agent_project_cursors(consumer_agent, project_id);
"""
