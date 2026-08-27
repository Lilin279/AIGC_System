from __future__ import annotations

import sqlite3
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("COURSEGRAPH_DATA_DIR", BACKEND_ROOT / "data"))
DATABASE_FILE = DATA_DIR / "coursegraph.db"
UPLOAD_DIR = DATA_DIR / "uploads"


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    name TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin', 'teacher', 'student')),
    organization TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS courses (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'published', 'archived')),
    owner_id TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    format TEXT NOT NULL,
    size INTEGER NOT NULL,
    parsed_chars INTEGER NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    storage_path TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS nodes (
    id TEXT PRIMARY KEY,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'concept',
    definition TEXT NOT NULL DEFAULT '',
    example TEXT NOT NULL DEFAULT '',
    resources_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS edges (
    id TEXT PRIMARY KEY,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    source TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    target TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    relation TEXT NOT NULL CHECK (relation IN ('contains', 'prerequisite', 'related')),
    label TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(course_id, source, target, relation)
);

CREATE TABLE IF NOT EXISTS learning_progress (
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    node_id TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    mastered INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(user_id, course_id, node_id)
);

CREATE INDEX IF NOT EXISTS idx_courses_owner_status ON courses(owner_id, status);
CREATE INDEX IF NOT EXISTS idx_documents_course ON documents(course_id);
CREATE INDEX IF NOT EXISTS idx_nodes_course ON nodes(course_id);
CREATE INDEX IF NOT EXISTS idx_edges_course ON edges(course_id);
CREATE INDEX IF NOT EXISTS idx_progress_user_course ON learning_progress(user_id, course_id);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
"""


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_FILE)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def initialize_schema() -> None:
    with connect() as connection:
        connection.executescript(SCHEMA)
        connection.execute("PRAGMA optimize")
