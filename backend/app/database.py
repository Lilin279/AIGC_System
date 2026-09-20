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

EXTENDED_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS organizations (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    code TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS departments (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(id),
    name TEXT NOT NULL,
    UNIQUE(organization_id, name)
);

CREATE TABLE IF NOT EXISTS teacher_applications (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    department TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK (status IN ('pending', 'approved', 'rejected')),
    reason TEXT NOT NULL DEFAULT '',
    reviewed_by TEXT REFERENCES users(id),
    reviewed_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS classrooms (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(id),
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    semester TEXT NOT NULL DEFAULT '',
    join_code TEXT NOT NULL UNIQUE,
    join_enabled INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('draft', 'active', 'closed')),
    primary_teacher_id TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS class_teachers (
    classroom_id TEXT NOT NULL REFERENCES classrooms(id) ON DELETE CASCADE,
    teacher_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT 'collaborator' CHECK (role IN ('primary', 'collaborator')),
    can_edit_course INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(classroom_id, teacher_id)
);

CREATE TABLE IF NOT EXISTS enrollments (
    classroom_id TEXT NOT NULL REFERENCES classrooms(id) ON DELETE CASCADE,
    student_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'left')),
    enrolled_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(classroom_id, student_id)
);

CREATE TABLE IF NOT EXISTS class_learning_progress (
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    classroom_id TEXT NOT NULL REFERENCES classrooms(id) ON DELETE CASCADE,
    node_id TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    mastered INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(user_id, classroom_id, node_id)
);

CREATE TABLE IF NOT EXISTS document_chunks (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    page_no INTEGER,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(document_id, chunk_index)
);

CREATE TABLE IF NOT EXISTS extraction_jobs (
    id TEXT PRIMARY KEY,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    requested_by TEXT NOT NULL REFERENCES users(id),
    document_ids_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'queued',
    progress INTEGER NOT NULL DEFAULT 0,
    mode TEXT NOT NULL DEFAULT 'mock',
    message TEXT NOT NULL DEFAULT '',
    candidate_version_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS graph_versions (
    id TEXT PRIMARY KEY,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    version_no INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('candidate', 'active', 'rejected', 'superseded')),
    trigger TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    graph_json TEXT NOT NULL,
    created_by TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(course_id, version_no)
);

CREATE TABLE IF NOT EXISTS node_sources (
    node_id TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    document_id TEXT REFERENCES documents(id) ON DELETE CASCADE,
    source_type TEXT NOT NULL DEFAULT 'aigc' CHECK (source_type IN ('aigc', 'manual', 'shared')),
    source_excerpt TEXT NOT NULL DEFAULT '',
    manual_override INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(node_id, document_id, source_type)
);

CREATE TABLE IF NOT EXISTS edge_sources (
    edge_id TEXT NOT NULL REFERENCES edges(id) ON DELETE CASCADE,
    document_id TEXT REFERENCES documents(id) ON DELETE CASCADE,
    source_type TEXT NOT NULL DEFAULT 'aigc' CHECK (source_type IN ('aigc', 'manual', 'shared')),
    manual_override INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(edge_id, document_id, source_type)
);

CREATE TABLE IF NOT EXISTS import_jobs (
    id TEXT PRIMARY KEY,
    classroom_id TEXT NOT NULL REFERENCES classrooms(id) ON DELETE CASCADE,
    requested_by TEXT NOT NULL REFERENCES users(id),
    status TEXT NOT NULL DEFAULT 'preview',
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    committed_at TEXT
);

CREATE TABLE IF NOT EXISTS tickets (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(id),
    creator_id TEXT NOT NULL REFERENCES users(id),
    category TEXT NOT NULL,
    severity TEXT NOT NULL,
    subject TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    assigned_admin_id TEXT REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ticket_messages (
    id TEXT PRIMARY KEY,
    ticket_id TEXT NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    author_id TEXT NOT NULL REFERENCES users(id),
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ticket_attachments (
    id TEXT PRIMARY KEY,
    ticket_id TEXT NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    message_id TEXT REFERENCES ticket_messages(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    size INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS notifications (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    link TEXT NOT NULL DEFAULT '',
    is_read INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(id),
    actor_id TEXT NOT NULL REFERENCES users(id),
    action TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    detail_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ai_usage_logs (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT 'deepseek',
    model TEXT NOT NULL,
    capability TEXT NOT NULL,
    status TEXT NOT NULL,
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    elapsed_ms INTEGER NOT NULL DEFAULT 0,
    error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS neo4j_sync_state (
    course_id TEXT PRIMARY KEY REFERENCES courses(id) ON DELETE CASCADE,
    version_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'syncing', 'synced', 'failed')),
    attempts INTEGER NOT NULL DEFAULT 0,
    sqlite_nodes INTEGER NOT NULL DEFAULT 0,
    sqlite_edges INTEGER NOT NULL DEFAULT 0,
    neo4j_nodes INTEGER NOT NULL DEFAULT 0,
    neo4j_edges INTEGER NOT NULL DEFAULT 0,
    message TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    synced_at TEXT
);

CREATE TABLE IF NOT EXISTS vector_index_state (
    course_id TEXT PRIMARY KEY REFERENCES courses(id) ON DELETE CASCADE,
    model TEXT NOT NULL DEFAULT '',
    fingerprint TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'synced', 'failed')),
    chunk_count INTEGER NOT NULL DEFAULT 0,
    message TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    synced_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_classrooms_course ON classrooms(course_id, status);
CREATE INDEX IF NOT EXISTS idx_class_teachers_teacher ON class_teachers(teacher_id, classroom_id);
CREATE INDEX IF NOT EXISTS idx_enrollments_student ON enrollments(student_id, status);
CREATE INDEX IF NOT EXISTS idx_class_progress_user ON class_learning_progress(user_id, classroom_id);
CREATE INDEX IF NOT EXISTS idx_chunks_course ON document_chunks(course_id, document_id);
CREATE INDEX IF NOT EXISTS idx_jobs_course_status ON extraction_jobs(course_id, status);
CREATE INDEX IF NOT EXISTS idx_versions_course ON graph_versions(course_id, version_no DESC);
CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ai_usage_created ON ai_usage_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_neo4j_sync_status ON neo4j_sync_state(status, updated_at);
CREATE INDEX IF NOT EXISTS idx_vector_index_status ON vector_index_state(status, updated_at);
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
        connection.executescript(EXTENDED_SCHEMA)
        _ensure_column(connection, "users", "username", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(connection, "users", "email", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(connection, "users", "phone", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(connection, "users", "avatar_url", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(connection, "users", "account_status", "TEXT NOT NULL DEFAULT 'active'")
        _ensure_column(connection, "users", "must_change_password", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(connection, "users", "student_no", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(connection, "users", "department", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(connection, "users", "title", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(connection, "users", "rejection_reason", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(connection, "users", "organization_id", "TEXT NOT NULL DEFAULT 'org_demo'")
        _ensure_column(connection, "courses", "organization_id", "TEXT NOT NULL DEFAULT 'org_demo'")
        _ensure_column(connection, "courses", "source_incomplete", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(connection, "courses", "active_version_id", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(connection, "documents", "status", "TEXT NOT NULL DEFAULT 'active'")
        _ensure_column(connection, "documents", "baseline_version_id", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(connection, "documents", "deleted_at", "TEXT")
        _ensure_column(connection, "node_sources", "page_no", "INTEGER")
        _ensure_column(connection, "node_sources", "confidence", "REAL NOT NULL DEFAULT 0")
        _ensure_column(connection, "node_sources", "reason", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(connection, "edge_sources", "page_no", "INTEGER")
        _ensure_column(connection, "edge_sources", "confidence", "REAL NOT NULL DEFAULT 0")
        _ensure_column(connection, "edge_sources", "reason", "TEXT NOT NULL DEFAULT ''")
        connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username ON users(username)")
        connection.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (2)")
        try:
            migrated = connection.execute("SELECT 1 FROM schema_migrations WHERE version = 3").fetchone()
            if not migrated:
                from app.services.retrieval import index_text

                connection.execute("DROP TABLE IF EXISTS document_chunks_fts")
                connection.execute(
                    "CREATE VIRTUAL TABLE document_chunks_fts USING fts5(chunk_id UNINDEXED, course_id UNINDEXED, tokens)"
                )
                for row in connection.execute("SELECT id, course_id, content FROM document_chunks").fetchall():
                    connection.execute(
                        "INSERT INTO document_chunks_fts(chunk_id, course_id, tokens) VALUES (?, ?, ?)",
                        (row["id"], row["course_id"], index_text(row["content"])),
                    )
                connection.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (3)")
            else:
                connection.execute(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS document_chunks_fts USING fts5(chunk_id UNINDEXED, course_id UNINDEXED, tokens)"
                )
        except sqlite3.OperationalError:
            pass
        connection.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (4)")
        connection.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (5)")
        connection.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (6)")
        connection.execute("PRAGMA optimize")


def _ensure_column(connection: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
