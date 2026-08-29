from __future__ import annotations

import json
import shutil
import sqlite3
import uuid
from pathlib import Path

from app.auth import hash_password, verify_password
from app.database import DATA_DIR, UPLOAD_DIR, connect, initialize_schema
from app.models import (
    Course,
    CourseCreate,
    CourseUpdate,
    DocumentInfo,
    GraphStats,
    KnowledgeEdge,
    KnowledgeEdgeCreate,
    KnowledgeEdgeUpdate,
    KnowledgeGraph,
    KnowledgeNode,
    KnowledgeNodeCreate,
    RegisterRequest,
    SourceReference,
    User,
)
from app.services.extractor import RELATION_LABELS, build_mock_graph


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_DIR = PROJECT_ROOT / "sample_data"
DEMO_USERS = (
    ("admin_demo", "admin", "Admin123!", "系统管理员", "金扬智能示范学校", "admin"),
    ("teacher_demo", "teacher", "Teacher123!", "李老师", "金扬智能示范学校", "teacher"),
    ("student_demo", "student", "Student123!", "王同学", "金扬智能示范学校", "student"),
)
SAMPLE_DOCUMENTS = {
    "python_intro": SAMPLE_DIR / "documents" / "python_intro.md",
    "database_systems": SAMPLE_DIR / "documents" / "database_systems.txt",
}


def _read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def init_store() -> None:
    initialize_schema()
    with connect() as connection:
        if connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            connection.executemany(
                """
                INSERT INTO users(id, username, password_hash, name, organization, role)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (user_id, username, hash_password(password), name, organization, role)
                    for user_id, username, password, name, organization, role in DEMO_USERS
                ],
            )
        if connection.execute("SELECT COUNT(*) FROM courses").fetchone()[0] == 0:
            _seed_courses(connection)
    from app.platform import initialize_extended_data
    initialize_extended_data()


def _seed_courses(connection: sqlite3.Connection) -> None:
    courses = _read_json(SAMPLE_DIR / "courses.json")["courses"]
    for course in courses:
        connection.execute(
            "INSERT INTO courses(id, name, description, status, owner_id) VALUES (?, ?, ?, ?, ?)",
            (course["id"], course["name"], course["description"], course.get("status", "published"), "teacher_demo"),
        )
        graph = _read_json(SAMPLE_DIR / "graphs" / f"{course['id']}.json")
        _insert_graph(connection, course["id"], KnowledgeGraph(**graph))
        document_path = SAMPLE_DOCUMENTS.get(course["id"])
        if document_path and document_path.exists():
            raw = document_path.read_bytes()
            content = document_path.read_text(encoding="utf-8")
            connection.execute(
                """
                INSERT INTO documents(id, course_id, filename, format, size, parsed_chars, content, storage_path)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"sample_{course['id']}", course["id"], document_path.name,
                    document_path.suffix.lstrip("."), len(raw), len(content), content, str(document_path),
                ),
            )


def reset_store() -> None:
    if DATA_DIR.exists():
        shutil.rmtree(DATA_DIR)
    init_store()


def register_student(payload: RegisterRequest) -> User:
    username = payload.username.strip().lower()
    name = payload.name.strip()
    if len(username) < 3:
        raise ValueError("用户名至少需要 3 个字符")
    if len(payload.password) < 8:
        raise ValueError("密码至少需要 8 个字符")
    if not name:
        raise ValueError("姓名不能为空")
    user = User(
        id=f"user_{uuid.uuid4().hex[:12]}", username=username, name=name, role="student",
        organization=payload.organization.strip() or "金扬智能示范学校", account_status="active",
    )
    try:
        with connect() as connection:
            connection.execute(
                """
                INSERT INTO users(id, username, password_hash, name, role, organization)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user.id, username, hash_password(payload.password), user.name, user.role, user.organization),
            )
    except sqlite3.IntegrityError as exc:
        raise ValueError("用户名已存在") from exc
    return user


def authenticate(username: str, password: str) -> User | None:
    with connect() as connection:
        row = connection.execute(
            """
            SELECT id, name, role, organization, username, email, phone, avatar_url,
                   account_status, must_change_password, student_no, department, title,
                   rejection_reason, password_hash
            FROM users WHERE username = ? AND is_active = 1 AND account_status != 'disabled'
            """,
            (username.strip().lower(),),
        ).fetchone()
    if not row or not verify_password(password, row["password_hash"]):
        return None
    values = dict(row)
    values.pop("password_hash")
    values["must_change_password"] = bool(values["must_change_password"])
    return User(**values)


def list_courses(user: User) -> list[Course]:
    where = ""
    parameters: tuple[str, ...] = ()
    if user.role == "student":
        where = """
        WHERE c.status = 'published' AND EXISTS (
          SELECT 1 FROM classrooms cl JOIN enrollments en ON en.classroom_id = cl.id
          WHERE cl.course_id = c.id AND cl.status = 'active'
            AND en.student_id = ? AND en.status = 'active'
        )
        """
        parameters = (user.id,)
    elif user.role == "teacher":
        where = """
        WHERE c.owner_id = ? OR EXISTS (
          SELECT 1 FROM classrooms cl JOIN class_teachers ct ON ct.classroom_id = cl.id
          WHERE cl.course_id = c.id AND ct.teacher_id = ?
        )
        """
        parameters = (user.id, user.id)
    query = f"""
        SELECT c.*, u.name AS owner_name,
            (SELECT COUNT(*) FROM documents d WHERE d.course_id = c.id) AS document_count,
            (SELECT COUNT(*) FROM nodes n WHERE n.course_id = c.id) AS node_count,
            (SELECT COUNT(*) FROM edges e WHERE e.course_id = c.id) AS edge_count,
            (SELECT COUNT(DISTINCT e.relation) FROM edges e WHERE e.course_id = c.id) AS relation_type_count
            ,(SELECT COUNT(*) FROM classrooms cl WHERE cl.course_id = c.id) AS classroom_count
            ,(SELECT COUNT(*) FROM enrollments en JOIN classrooms cl ON cl.id = en.classroom_id
              WHERE cl.course_id = c.id AND en.status = 'active') AS student_count
        FROM courses c JOIN users u ON u.id = c.owner_id
        {where}
        ORDER BY c.updated_at DESC, c.created_at DESC
    """
    with connect() as connection:
        rows = connection.execute(query, parameters).fetchall()
    return [_course_from_row(row) for row in rows]


def get_course(course_id: str, user: User) -> Course:
    courses = [course for course in list_courses(user) if course.id == course_id]
    if not courses:
        raise KeyError("课程不存在或无权访问")
    return courses[0]


def add_course(payload: CourseCreate, user: User) -> Course:
    _require_role(user, "teacher", "admin")
    if not payload.name.strip():
        raise ValueError("课程名称不能为空")
    if payload.status == "published":
        raise ValueError("新课程需先保存为草稿，完善图谱后再发布")
    course_id = f"course_{uuid.uuid4().hex[:10]}"
    with connect() as connection:
        connection.execute(
            "INSERT INTO courses(id, name, description, status, owner_id) VALUES (?, ?, ?, ?, ?)",
            (course_id, payload.name.strip(), payload.description.strip(), payload.status, user.id),
        )
    return get_course(course_id, user)


def update_course(course_id: str, payload: CourseUpdate, user: User) -> Course:
    _assert_own_course(course_id, user)
    if not payload.name.strip():
        raise ValueError("课程名称不能为空")
    if payload.status == "published":
        _validate_publish(course_id)
    with connect() as connection:
        connection.execute(
            "UPDATE courses SET name = ?, description = ?, status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (payload.name.strip(), payload.description.strip(), payload.status, course_id),
        )
    return get_course(course_id, user)


def delete_course(course_id: str, user: User) -> dict:
    _assert_own_course(course_id, user)
    with connect() as connection:
        connection.execute("DELETE FROM courses WHERE id = ?", (course_id,))
    course_upload_dir = UPLOAD_DIR / course_id
    if course_upload_dir.exists():
        shutil.rmtree(course_upload_dir)
    return {"deleted": course_id}


def get_graph(course_id: str, user: User) -> KnowledgeGraph:
    _assert_read_course(course_id, user)
    with connect() as connection:
        if user.role == "student":
            nodes = connection.execute(
                """
                SELECT n.*, COALESCE(p.mastered, 0) AS mastered
                FROM nodes n LEFT JOIN learning_progress p
                  ON p.node_id = n.id AND p.course_id = n.course_id AND p.user_id = ?
                WHERE n.course_id = ? ORDER BY n.created_at, n.id
                """,
                (user.id, course_id),
            ).fetchall()
        else:
            nodes = connection.execute(
                "SELECT n.*, 0 AS mastered FROM nodes n WHERE n.course_id = ? ORDER BY n.created_at, n.id",
                (course_id,),
            ).fetchall()
        edges = connection.execute(
            "SELECT id, source, target, relation, label FROM edges WHERE course_id = ? ORDER BY created_at, id",
            (course_id,),
        ).fetchall()
        node_sources = connection.execute(
            """
            SELECT ns.node_id, ns.document_id, ns.source_type, ns.source_excerpt, ns.page_no,
                   ns.confidence, ns.reason, COALESCE(d.filename, '') AS filename
            FROM node_sources ns
            LEFT JOIN documents d ON d.id = ns.document_id
            WHERE ns.node_id IN (SELECT id FROM nodes WHERE course_id = ?)
            ORDER BY ns.confidence DESC
            """,
            (course_id,),
        ).fetchall()
        edge_sources = connection.execute(
            """
            SELECT es.edge_id, es.document_id, es.source_type, '' AS source_excerpt, es.page_no,
                   es.confidence, es.reason, COALESCE(d.filename, '') AS filename
            FROM edge_sources es
            LEFT JOIN documents d ON d.id = es.document_id
            WHERE es.edge_id IN (SELECT id FROM edges WHERE course_id = ?)
            ORDER BY es.confidence DESC
            """,
            (course_id,),
        ).fetchall()
    node_source_map = _source_map(node_sources, "node_id")
    edge_source_map = _source_map(edge_sources, "edge_id")
    return KnowledgeGraph(
        nodes=[_node_from_row(row).model_copy(update={"source_refs": node_source_map.get(row["id"], [])}) for row in nodes],
        edges=[KnowledgeEdge(**dict(row), source_refs=edge_source_map.get(row["id"], [])) for row in edges],
    )


def save_document(course_id: str, filename: str, fmt: str, content: str, raw: bytes, user: User) -> DocumentInfo:
    _assert_manage_course(course_id, user)
    doc_id = f"doc_{uuid.uuid4().hex[:10]}"
    safe_name = Path(filename).name
    course_upload_dir = UPLOAD_DIR / course_id
    course_upload_dir.mkdir(parents=True, exist_ok=True)
    storage_path = course_upload_dir / f"{doc_id}_{safe_name}"
    storage_path.write_bytes(raw)
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO documents(id, course_id, filename, format, size, parsed_chars, content, storage_path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (doc_id, course_id, safe_name, fmt, len(raw), len(content), content, str(storage_path)),
        )
    return _document_by_id(course_id, doc_id)


def list_documents(course_id: str, user: User) -> list[DocumentInfo]:
    _assert_read_course(course_id, user)
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT d.id, d.filename, d.format, d.size, d.parsed_chars, d.created_at, d.status,
              (SELECT COUNT(DISTINCT ns.node_id) FROM node_sources ns WHERE ns.document_id = d.id) AS source_node_count
            FROM documents d WHERE d.course_id = ? AND d.status = 'active' ORDER BY d.created_at DESC
            """,
            (course_id,),
        ).fetchall()
    return [DocumentInfo(**dict(row)) for row in rows]


def delete_document(course_id: str, document_id: str, user: User) -> dict:
    _assert_manage_course(course_id, user)
    with connect() as connection:
        row = connection.execute(
            "SELECT storage_path FROM documents WHERE id = ? AND course_id = ?", (document_id, course_id)
        ).fetchone()
        if not row:
            raise KeyError("资料不存在")
        connection.execute("DELETE FROM documents WHERE id = ?", (document_id,))
    path = Path(row["storage_path"])
    if path.is_file() and UPLOAD_DIR in path.parents:
        path.unlink()
    return {"deleted": document_id}


def extract_course_graph(course_id: str, user: User) -> KnowledgeGraph:
    _assert_manage_course(course_id, user)
    with connect() as connection:
        course = connection.execute("SELECT name FROM courses WHERE id = ?", (course_id,)).fetchone()
        docs = [dict(row) for row in connection.execute(
            "SELECT filename, format, content FROM documents WHERE course_id = ?", (course_id,)
        ).fetchall()]
        graph = build_mock_graph(course["name"], docs)
        connection.execute("DELETE FROM edges WHERE course_id = ?", (course_id,))
        connection.execute("DELETE FROM nodes WHERE course_id = ?", (course_id,))
        _insert_graph(connection, course_id, graph)
        connection.execute("UPDATE courses SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (course_id,))
    return get_graph(course_id, user)


def add_node(course_id: str, payload: KnowledgeNodeCreate, user: User) -> KnowledgeNode:
    _assert_manage_course(course_id, user)
    if not payload.name.strip():
        raise ValueError("知识点名称不能为空")
    node = KnowledgeNode(id=f"node_{uuid.uuid4().hex[:10]}", **payload.model_dump())
    with connect() as connection:
        _insert_node(connection, course_id, node)
        connection.execute(
            "INSERT INTO node_sources(node_id, document_id, source_type, manual_override) VALUES (?, NULL, 'manual', 1)",
            (node.id,),
        )
    return node.model_copy(update={"mastered": False})


def update_node(course_id: str, node_id: str, payload: KnowledgeNodeCreate, user: User) -> KnowledgeNode:
    _assert_manage_course(course_id, user)
    if not payload.name.strip():
        raise ValueError("知识点名称不能为空")
    with connect() as connection:
        cursor = connection.execute(
            """
            UPDATE nodes SET name = ?, type = ?, definition = ?, example = ?, resources_json = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND course_id = ?
            """,
            (
                payload.name.strip(), payload.type.strip() or "concept", payload.definition.strip(),
                payload.example.strip(), json.dumps(payload.resources, ensure_ascii=False), node_id, course_id,
            ),
        )
        if cursor.rowcount == 0:
            raise KeyError("知识点不存在")
        connection.execute("UPDATE node_sources SET manual_override = 1 WHERE node_id = ?", (node_id,))
        connection.execute("DELETE FROM node_sources WHERE node_id = ? AND document_id IS NULL", (node_id,))
        connection.execute(
            "INSERT INTO node_sources(node_id, document_id, source_type, manual_override) VALUES (?, NULL, 'manual', 1)",
            (node_id,),
        )
    return KnowledgeNode(id=node_id, **payload.model_dump()).model_copy(update={"mastered": False})


def delete_node(course_id: str, node_id: str, user: User) -> dict:
    _assert_manage_course(course_id, user)
    with connect() as connection:
        cursor = connection.execute("DELETE FROM nodes WHERE id = ? AND course_id = ?", (node_id, course_id))
        if cursor.rowcount == 0:
            raise KeyError("知识点不存在")
    return {"deleted": node_id}


def add_edge(course_id: str, payload: KnowledgeEdgeCreate, user: User) -> KnowledgeEdge:
    _assert_manage_course(course_id, user)
    _validate_edge(course_id, payload.source, payload.target)
    label = payload.label.strip() or RELATION_LABELS[payload.relation]
    edge = KnowledgeEdge(
        id=f"edge_{uuid.uuid4().hex[:10]}", source=payload.source, target=payload.target,
        relation=payload.relation, label=label,
    )
    try:
        with connect() as connection:
            _insert_edge(connection, course_id, edge)
            connection.execute(
                "INSERT INTO edge_sources(edge_id, document_id, source_type, manual_override) VALUES (?, NULL, 'manual', 1)",
                (edge.id,),
            )
    except sqlite3.IntegrityError as exc:
        raise ValueError("相同知识点之间已存在该类型关系") from exc
    return edge


def update_edge(course_id: str, edge_id: str, payload: KnowledgeEdgeUpdate, user: User) -> KnowledgeEdge:
    _assert_manage_course(course_id, user)
    _validate_edge(course_id, payload.source, payload.target)
    label = payload.label.strip() or RELATION_LABELS[payload.relation]
    try:
        with connect() as connection:
            cursor = connection.execute(
                "UPDATE edges SET source = ?, target = ?, relation = ?, label = ? WHERE id = ? AND course_id = ?",
                (payload.source, payload.target, payload.relation, label, edge_id, course_id),
            )
            if cursor.rowcount == 0:
                raise KeyError("关系不存在")
            connection.execute("UPDATE edge_sources SET manual_override = 1 WHERE edge_id = ?", (edge_id,))
            connection.execute("DELETE FROM edge_sources WHERE edge_id = ? AND document_id IS NULL", (edge_id,))
            connection.execute(
                "INSERT INTO edge_sources(edge_id, document_id, source_type, manual_override) VALUES (?, NULL, 'manual', 1)",
                (edge_id,),
            )
    except sqlite3.IntegrityError as exc:
        raise ValueError("相同知识点之间已存在该类型关系") from exc
    return KnowledgeEdge(id=edge_id, source=payload.source, target=payload.target, relation=payload.relation, label=label)


def delete_edge(course_id: str, edge_id: str, user: User) -> dict:
    _assert_manage_course(course_id, user)
    with connect() as connection:
        cursor = connection.execute("DELETE FROM edges WHERE id = ? AND course_id = ?", (edge_id, course_id))
        if cursor.rowcount == 0:
            raise KeyError("关系不存在")
    return {"deleted": edge_id}


def set_progress(course_id: str, node_id: str, mastered: bool, user: User) -> KnowledgeNode:
    if user.role != "student":
        raise PermissionError("仅学生可以记录学习进度")
    _assert_read_course(course_id, user)
    with connect() as connection:
        node = connection.execute(
            "SELECT * FROM nodes WHERE id = ? AND course_id = ?", (node_id, course_id)
        ).fetchone()
        if not node:
            raise KeyError("知识点不存在")
        connection.execute(
            """
            INSERT INTO learning_progress(user_id, course_id, node_id, mastered, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id, course_id, node_id)
            DO UPDATE SET mastered = excluded.mastered, updated_at = CURRENT_TIMESTAMP
            """,
            (user.id, course_id, node_id, int(mastered)),
        )
    return _node_from_row({**dict(node), "mastered": int(mastered)})


def mastered_node_ids(course_id: str, user: User) -> list[str]:
    _assert_read_course(course_id, user)
    with connect() as connection:
        rows = connection.execute(
            "SELECT node_id FROM learning_progress WHERE user_id = ? AND course_id = ? AND mastered = 1",
            (user.id, course_id),
        ).fetchall()
    return [row["node_id"] for row in rows]


def _course_from_row(row: sqlite3.Row) -> Course:
    return Course(
        id=row["id"], name=row["name"], description=row["description"], status=row["status"],
        owner_id=row["owner_id"], owner_name=row["owner_name"], document_count=row["document_count"],
        stats=GraphStats(nodes=row["node_count"], edges=row["edge_count"], relation_types=row["relation_type_count"]),
        classroom_count=row["classroom_count"], student_count=row["student_count"],
        source_incomplete=bool(row["source_incomplete"]),
    )


def _node_from_row(row: sqlite3.Row | dict) -> KnowledgeNode:
    return KnowledgeNode(
        id=row["id"], name=row["name"], type=row["type"], definition=row["definition"],
        example=row["example"], resources=json.loads(row["resources_json"] or "[]"), mastered=bool(row["mastered"]),
    )


def _source_map(rows: list[sqlite3.Row], owner_field: str) -> dict[str, list[SourceReference]]:
    result: dict[str, list[SourceReference]] = {}
    for row in rows:
        result.setdefault(row[owner_field], []).append(
            SourceReference(
                document_id=row["document_id"] or "", filename=row["filename"], source_type=row["source_type"],
                page_no=row["page_no"], excerpt=row["source_excerpt"], confidence=float(row["confidence"] or 0),
                reason=row["reason"],
            )
        )
    return result


def _document_by_id(course_id: str, document_id: str) -> DocumentInfo:
    with connect() as connection:
        row = connection.execute(
            """
            SELECT d.id, d.filename, d.format, d.size, d.parsed_chars, d.created_at, d.status,
              (SELECT COUNT(DISTINCT ns.node_id) FROM node_sources ns WHERE ns.document_id = d.id) AS source_node_count
            FROM documents d WHERE d.id = ? AND d.course_id = ?
            """,
            (document_id, course_id),
        ).fetchone()
    if not row:
        raise KeyError("资料不存在")
    return DocumentInfo(**dict(row))


def _insert_graph(connection: sqlite3.Connection, course_id: str, graph: KnowledgeGraph) -> None:
    for node in graph.nodes:
        _insert_node(connection, course_id, node)
    for edge in graph.edges:
        _insert_edge(connection, course_id, edge)


def _insert_node(connection: sqlite3.Connection, course_id: str, node: KnowledgeNode) -> None:
    connection.execute(
        """
        INSERT INTO nodes(id, course_id, name, type, definition, example, resources_json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (node.id, course_id, node.name, node.type, node.definition, node.example, json.dumps(node.resources, ensure_ascii=False)),
    )


def _insert_edge(connection: sqlite3.Connection, course_id: str, edge: KnowledgeEdge) -> None:
    connection.execute(
        "INSERT INTO edges(id, course_id, source, target, relation, label) VALUES (?, ?, ?, ?, ?, ?)",
        (edge.id, course_id, edge.source, edge.target, edge.relation, edge.label),
    )


def _assert_read_course(course_id: str, user: User) -> None:
    with connect() as connection:
        row = connection.execute("SELECT owner_id, status FROM courses WHERE id = ?", (course_id,)).fetchone()
    if not row:
        raise KeyError("课程不存在")
    if user.role == "admin":
        return
    if user.role == "teacher" and row["owner_id"] == user.id:
        return
    if user.role == "student" and row["status"] == "published":
        with connect() as connection:
            enrolled = connection.execute(
                """
                SELECT 1 FROM classrooms cl JOIN enrollments en ON en.classroom_id = cl.id
                WHERE cl.course_id = ? AND cl.status = 'active' AND en.student_id = ? AND en.status = 'active'
                """,
                (course_id, user.id),
            ).fetchone()
        if enrolled:
            return
    raise PermissionError("无权访问该课程")


def _assert_manage_course(course_id: str, user: User) -> None:
    _require_role(user, "teacher", "admin")
    with connect() as connection:
        row = connection.execute("SELECT owner_id FROM courses WHERE id = ?", (course_id,)).fetchone()
        collaborator = connection.execute(
            """
            SELECT 1 FROM classrooms cl JOIN class_teachers ct ON ct.classroom_id = cl.id
            WHERE cl.course_id = ? AND ct.teacher_id = ? AND ct.can_edit_course = 1
            """,
            (course_id, user.id),
        ).fetchone()
    if not row:
        raise KeyError("课程不存在")
    if user.role != "admin" and row["owner_id"] != user.id and not collaborator:
        raise PermissionError("只能管理自己开设或获授权编辑的课程")


def _assert_own_course(course_id: str, user: User) -> None:
    _require_role(user, "teacher", "admin")
    with connect() as connection:
        row = connection.execute("SELECT owner_id FROM courses WHERE id = ?", (course_id,)).fetchone()
    if not row:
        raise KeyError("课程不存在")
    if user.role != "admin" and row["owner_id"] != user.id:
        raise PermissionError("只有课程主教师可以修改课程信息或归档课程")


def _require_role(user: User, *roles: str) -> None:
    if user.role not in roles:
        raise PermissionError("当前角色无权执行此操作")


def _validate_publish(course_id: str) -> None:
    with connect() as connection:
        node_count = connection.execute("SELECT COUNT(*) FROM nodes WHERE course_id = ?", (course_id,)).fetchone()[0]
        edge_count = connection.execute("SELECT COUNT(*) FROM edges WHERE course_id = ?", (course_id,)).fetchone()[0]
    if node_count < 3 or edge_count < 1:
        raise ValueError("发布前至少需要 3 个知识点和 1 条知识关系")


def _validate_edge(course_id: str, source: str, target: str) -> None:
    if source == target:
        raise ValueError("关系的源知识点和目标知识点不能相同")
    with connect() as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM nodes WHERE course_id = ? AND id IN (?, ?)", (course_id, source, target)
        ).fetchone()[0]
    if count != 2:
        raise ValueError("关系两端必须是当前课程中的知识点")
