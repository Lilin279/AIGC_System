from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


TEST_DATA = tempfile.TemporaryDirectory()
os.environ["COURSEGRAPH_DATA_DIR"] = str(Path(TEST_DATA.name) / "data")
# API 回归必须保持离线，避免开发者本机配置 Key 后测试误调用真实服务。
os.environ["DEEPSEEK_API_KEY"] = ""
os.environ["NEO4J_HTTP_URL"] = ""
os.environ["HYBRID_RAG_ENABLED"] = "false"

from fastapi.testclient import TestClient  # noqa: E402

from app import storage  # noqa: E402
from app.main import app  # noqa: E402


class ApiTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        storage.init_store()
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.close()
        TEST_DATA.cleanup()

    def login(self, username: str, password: str) -> str:
        response = self.client.post("/api/auth/login", json={"username": username, "password": password})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["token"]

    @staticmethod
    def headers(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def test_student_only_sees_joined_classes_and_courses(self) -> None:
        registered = self.client.post(
            "/api/auth/register",
            json={"username": "class_student", "password": "Password123!", "name": "班级学生", "organization": "测试学校"},
        )
        self.assertEqual(registered.status_code, 201, registered.text)
        headers = self.headers(registered.json()["token"])
        self.assertEqual(self.client.get("/api/classrooms", headers=headers).json(), [])
        self.assertEqual(self.client.get("/api/courses", headers=headers).json(), [])

        teacher = self.login("teacher", "Teacher123!")
        classroom = self.client.get("/api/classrooms", headers=self.headers(teacher)).json()[0]
        joined = self.client.post(
            "/api/classrooms/join", headers=headers, json={"join_code": classroom["join_code"]}
        )
        self.assertEqual(joined.status_code, 200, joined.text)
        visible = self.client.get("/api/courses", headers=headers).json()
        self.assertEqual({item["id"] for item in visible}, {classroom["course_id"]})

    def test_teacher_registration_requires_admin_review(self) -> None:
        application = self.client.post(
            "/api/auth/register/teacher",
            json={
                "username": "teacher_pending", "password": "Password123!", "name": "待审教师",
                "organization": "测试学校", "email": "teacher@example.com", "department": "计算机学院", "title": "讲师",
            },
        )
        self.assertEqual(application.status_code, 201, application.text)
        pending_headers = self.headers(application.json()["token"])
        blocked = self.client.get("/api/courses", headers=pending_headers)
        self.assertEqual(blocked.status_code, 403)

        admin = self.login("admin", "Admin123!")
        pending_users = self.client.get(
            "/api/admin/users?role=teacher&status=pending", headers=self.headers(admin)
        ).json()
        teacher = next(item for item in pending_users if item["username"] == "teacher_pending")
        reviewed = self.client.post(
            f"/api/admin/teachers/{teacher['id']}/review",
            headers=self.headers(admin), json={"action": "approve", "reason": ""},
        )
        self.assertEqual(reviewed.status_code, 200, reviewed.text)
        self.assertEqual(reviewed.json()["account_status"], "active")
        self.assertEqual(self.client.get("/api/courses", headers=pending_headers).status_code, 200)

    def test_registration_requires_organization(self) -> None:
        student = self.client.post(
            "/api/auth/register",
            json={"username": "student_without_org", "password": "Password123!", "name": "未填写学校学生"},
        )
        self.assertEqual(student.status_code, 400, student.text)
        self.assertEqual(student.json()["detail"], "学校名称不能为空")

        teacher = self.client.post(
            "/api/auth/register/teacher",
            json={"username": "teacher_without_org", "password": "Password123!", "name": "未填写学校教师"},
        )
        self.assertEqual(teacher.status_code, 400, teacher.text)
        self.assertEqual(teacher.json()["detail"], "学校名称不能为空")

    def test_class_progress_isolated_and_ticket_visible(self) -> None:
        first = self.login("student", "Student123!")
        classroom = self.client.get("/api/classrooms", headers=self.headers(first)).json()[0]
        graph = self.client.get(f"/api/classrooms/{classroom['id']}/graph", headers=self.headers(first)).json()
        node_id = graph["nodes"][0]["id"]
        marked = self.client.put(
            f"/api/classrooms/{classroom['id']}/progress/{node_id}",
            headers=self.headers(first), json={"mastered": True},
        )
        self.assertEqual(marked.status_code, 200, marked.text)

        second = self.client.post(
            "/api/auth/register",
            json={"username": "progress_student", "password": "Password123!", "name": "进度学生", "organization": "测试学校"},
        )
        second_headers = self.headers(second.json()["token"])
        self.client.post("/api/classrooms/join", headers=second_headers, json={"join_code": classroom["join_code"]})
        second_graph = self.client.get(f"/api/classrooms/{classroom['id']}/graph", headers=second_headers).json()
        self.assertFalse(next(node for node in second_graph["nodes"] if node["id"] == node_id)["mastered"])

        created = self.client.post(
            "/api/tickets", headers=second_headers,
            json={"category": "graph", "severity": "high", "subject": "图谱节点异常", "description": "节点详情无法正常显示。"},
        )
        self.assertEqual(created.status_code, 201, created.text)
        admin = self.login("admin", "Admin123!")
        admin_ids = {item["id"] for item in self.client.get("/api/tickets", headers=self.headers(admin)).json()}
        self.assertIn(created.json()["id"], admin_ids)

    def test_document_candidate_version_and_selective_rollback(self) -> None:
        teacher = self.login("teacher", "Teacher123!")
        headers = self.headers(teacher)
        course = self.client.post(
            "/api/courses", headers=headers,
            json={"name": "算法设计测试课", "description": "图谱生命周期测试", "status": "draft"},
        )
        self.assertEqual(course.status_code, 201, course.text)
        course_id = course.json()["id"]
        uploaded = self.client.post(
            f"/api/courses/{course_id}/documents", headers=headers,
            files={"file": ("algorithms.md", b"# Sorting\nBubble sort compares adjacent values.\n# Graph\nBreadth first search uses a queue.", "text/markdown")},
        )
        self.assertEqual(uploaded.status_code, 201, uploaded.text)
        document_id = uploaded.json()["id"]
        job = self.client.post(f"/api/courses/{course_id}/extract", headers=headers)
        self.assertEqual(job.status_code, 202, job.text)
        job_state = self.client.get(f"/api/extraction-jobs/{job.json()['id']}", headers=headers).json()
        self.assertEqual(job_state["status"], "review")
        version_id = job_state["candidate_version_id"]
        accepted = self.client.post(
            f"/api/courses/{course_id}/graph/versions/{version_id}/accept", headers=headers
        )
        self.assertEqual(accepted.status_code, 200, accepted.text)
        graph = self.client.get(f"/api/courses/{course_id}/graph", headers=headers).json()
        self.assertGreaterEqual(len(graph["nodes"]), 3)
        self.assertTrue(any(node["source_refs"] for node in graph["nodes"]))
        self.assertTrue(any(
            reference["document_id"] == document_id
            for node in graph["nodes"] for reference in node["source_refs"]
        ))

        impact = self.client.get(
            f"/api/courses/{course_id}/documents/{document_id}/impact", headers=headers
        ).json()
        self.assertGreater(impact["removable_nodes"], 0)
        deleted = self.client.delete(
            f"/api/courses/{course_id}/documents/{document_id}?rollback_graph=true", headers=headers
        )
        self.assertEqual(deleted.status_code, 200, deleted.text)
        rolled_back = self.client.get(f"/api/courses/{course_id}/graph", headers=headers).json()
        self.assertEqual(rolled_back["nodes"], [])

    def test_uploaded_material_adds_nodes_without_replacing_existing_graph(self) -> None:
        teacher = self.login("teacher", "Teacher123!")
        headers = self.headers(teacher)
        course_id = "database_systems"
        original = self.client.get(f"/api/courses/{course_id}/graph", headers=headers).json()
        original_names = {node["name"] for node in original["nodes"]}
        material = """# 编译原理扩展
词法分析用于把字符流转换为记号流。
语法分析根据文法构造分析树。
语义分析检查类型与作用域。
中间代码生成连接前端与后端。
代码优化改善程序执行效率。
目标代码生成面向具体机器指令。
""".encode("utf-8")
        uploaded = self.client.post(
            f"/api/courses/{course_id}/documents", headers=headers,
            files={"file": ("compiler-extension.md", material, "text/markdown")},
        )
        self.assertEqual(uploaded.status_code, 201, uploaded.text)
        document_id = uploaded.json()["id"]
        job = self.client.post(f"/api/courses/{course_id}/extract", headers=headers)
        self.assertEqual(job.status_code, 202, job.text)
        job_state = self.client.get(f"/api/extraction-jobs/{job.json()['id']}", headers=headers).json()
        self.assertEqual(job_state["status"], "review")
        self.assertIn("新增", job_state["message"])
        version_id = job_state["candidate_version_id"]
        candidate = self.client.get(
            f"/api/courses/{course_id}/graph/versions/{version_id}", headers=headers
        ).json()["graph"]
        candidate_names = {node["name"] for node in candidate["nodes"]}
        self.assertTrue(original_names.issubset(candidate_names))
        self.assertGreater(len(candidate_names), len(original_names))

        accepted = self.client.post(
            f"/api/courses/{course_id}/graph/versions/{version_id}/accept", headers=headers
        )
        self.assertEqual(accepted.status_code, 200, accepted.text)
        impact = self.client.get(
            f"/api/courses/{course_id}/documents/{document_id}/impact", headers=headers
        ).json()
        self.assertGreater(impact["removable_nodes"], 0)
        deleted = self.client.delete(
            f"/api/courses/{course_id}/documents/{document_id}?rollback_graph=true", headers=headers
        )
        self.assertEqual(deleted.status_code, 200, deleted.text)
        restored = self.client.get(f"/api/courses/{course_id}/graph", headers=headers).json()
        self.assertEqual({node["name"] for node in restored["nodes"]}, original_names)

    def test_document_change_invalidates_candidate_and_requests_reextract(self) -> None:
        teacher = self.login("teacher", "Teacher123!")
        headers = self.headers(teacher)
        course = self.client.post(
            "/api/courses", headers=headers,
            json={"name": "编译原理联动测试", "description": "候选失效测试", "status": "draft"},
        ).json()
        course_id = course["id"]
        first = self.client.post(
            f"/api/courses/{course_id}/documents", headers=headers,
            files={"file": ("lexer.md", "# 词法分析\n记号流与有限自动机。".encode("utf-8"), "text/markdown")},
        ).json()
        self.client.post(
            f"/api/courses/{course_id}/documents", headers=headers,
            files={"file": ("parser.md", "# 语法分析\n文法、分析树与语法制导翻译。".encode("utf-8"), "text/markdown")},
        )
        job = self.client.post(f"/api/courses/{course_id}/extract", headers=headers).json()
        job_state = self.client.get(f"/api/extraction-jobs/{job['id']}", headers=headers).json()
        self.assertEqual(job_state["status"], "review")

        deleted = self.client.delete(
            f"/api/courses/{course_id}/documents/{first['id']}?rollback_graph=true", headers=headers
        )
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertTrue(deleted.json()["needs_reextract"])
        invalidated = self.client.get(f"/api/extraction-jobs/{job['id']}", headers=headers).json()
        self.assertEqual(invalidated["status"], "completed")
        self.assertIn("失效", invalidated["message"])
        versions = self.client.get(
            f"/api/courses/{course_id}/graph/versions", headers=headers
        ).json()
        candidate = next(item for item in versions if item["id"] == job_state["candidate_version_id"])
        self.assertEqual(candidate["status"], "rejected")

    def test_csv_import_preview_commit_and_forced_password_change(self) -> None:
        teacher = self.login("teacher", "Teacher123!")
        headers = self.headers(teacher)
        classroom = self.client.get("/api/classrooms", headers=headers).json()[0]
        csv_data = "学号,姓名,邮箱,手机号\n20269901,导入学生,import@example.com,13800000000\n,错误行,,\n".encode("utf-8-sig")
        preview = self.client.post(
            f"/api/classrooms/{classroom['id']}/imports/preview", headers=headers,
            files={"file": ("students.csv", csv_data, "text/csv")},
        )
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertEqual(preview.json()["valid"], 1)
        self.assertEqual(preview.json()["invalid"], 1)
        committed = self.client.post(f"/api/imports/{preview.json()['job_id']}/commit", headers=headers)
        self.assertEqual(committed.status_code, 200, committed.text)
        credential = committed.json()["credentials"][0]
        login = self.client.post(
            "/api/auth/login", json={"username": credential["student_no"], "password": credential["temporary_password"]}
        )
        self.assertTrue(login.json()["user"]["must_change_password"])
        blocked = self.client.get("/api/classrooms", headers=self.headers(login.json()["token"]))
        self.assertEqual(blocked.status_code, 403)

    def test_ai_status_never_exposes_key(self) -> None:
        teacher = self.login("teacher", "Teacher123!")
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": ""}, clear=False):
            response = self.client.get("/api/ai/status", headers=self.headers(teacher))
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertFalse(payload["configured"])
        self.assertEqual(payload["mode"], "offline")
        self.assertNotIn("key", json.dumps(payload).lower())

    def test_truncated_repair_creates_review_candidate_without_publishing(self) -> None:
        from app.services import deepseek

        headers = self.headers(self.login("teacher", "Teacher123!"))
        course = self.client.post("/api/courses", headers=headers, json={"name": "补全降级回归"})
        self.assertEqual(course.status_code, 201, course.text)
        course_id = course.json()["id"]
        uploaded = self.client.post(
            f"/api/courses/{course_id}/documents", headers=headers,
            files={"file": ("chapter.md", "变量保存数据".encode("utf-8"), "text/markdown")},
        )
        self.assertEqual(uploaded.status_code, 201, uploaded.text)
        initial = json.dumps({"nodes": [{
            "name": "变量", "definition": "变量保存数据",
            "sources": [{"document_id": uploaded.json()["id"], "excerpt": "变量保存数据"}],
        }], "edges": []})
        with (
            patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}),
            patch.object(deepseek, "_chat", side_effect=[initial, deepseek.DeepSeekTruncatedError("输出被截断")]),
        ):
            response = self.client.post(f"/api/courses/{course_id}/extract", headers=headers)
        self.assertEqual(response.status_code, 202, response.text)
        job = self.client.get(f"/api/extraction-jobs/{response.json()['id']}", headers=headers).json()
        self.assertEqual(job["status"], "review")
        self.assertIn("已保留首次有效抽取结果", job["message"])
        self.assertIn("未达到 20", job["message"])
        candidate = self.client.get(
            f"/api/courses/{course_id}/graph/versions/{job['candidate_version_id']}", headers=headers,
        ).json()
        self.assertEqual(candidate["status"], "candidate")
        self.assertIn("自动补全未完成", candidate["summary"])
        self.assertEqual(candidate["graph"]["nodes"][0]["name"], "变量")
        self.assertEqual(candidate["graph"]["nodes"][0]["source_refs"][0]["document_id"], uploaded.json()["id"])
        self.assertEqual(self.client.get(f"/api/courses/{course_id}/graph", headers=headers).json()["nodes"], [])

    def test_bm25_evidence_is_course_scoped_and_refuses_unknown_questions(self) -> None:
        teacher = self.login("teacher", "Teacher123!")
        headers = self.headers(teacher)
        unique_phrase = "预测分析表冲突消解标记"
        uploaded = self.client.post(
            "/api/courses/python_intro/documents", headers=headers,
            files={"file": ("bm25-evidence.md", f"# LR 分析\n{unique_phrase}用于验证中文检索。".encode("utf-8"), "text/markdown")},
        )
        self.assertEqual(uploaded.status_code, 201, uploaded.text)

        answer = self.client.post(
            "/api/courses/python_intro/qa", headers=headers, json={"question": unique_phrase},
        )
        self.assertEqual(answer.status_code, 200, answer.text)
        document_evidence = [item for item in answer.json()["evidence"] if item["type"] == "document"]
        self.assertTrue(document_evidence, answer.text)
        self.assertEqual(document_evidence[0]["source"], "bm25-evidence.md")
        self.assertEqual(answer.json()["mode"], "offline-graphrag")

        isolated = self.client.post(
            "/api/courses/database_systems/qa", headers=headers, json={"question": unique_phrase},
        ).json()
        self.assertFalse(any(item.get("source") == "bm25-evidence.md" for item in isolated["evidence"]))
        self.assertEqual(isolated["confidence"], "low")

        unknown = self.client.post(
            "/api/courses/python_intro/qa", headers=headers,
            json={"question": "zxqv nebula horticulture checksum 94817"},
        ).json()
        self.assertIn("没有足够证据", unknown["answer"])

    def test_hybrid_graphrag_exposes_component_scores_and_mode(self) -> None:
        teacher = self.login("teacher", "Teacher123!")
        vector_hit = {
            "id": "vector_chunk",
            "source": "python_intro.md",
            "excerpt": "变量用于保存程序运行中的数据。",
            "type": "document",
            "document_id": "doc_python",
            "vector_score": 0.91,
            "source_score": 0.8,
            "vector_backend": "qdrant",
        }
        with (
            patch.dict(os.environ, {"HYBRID_RAG_ENABLED": "true", "HYBRID_RAG_RERANK_ENABLED": "false"}),
            patch("app.services.hybrid_retrieval.semantic_candidates", return_value=([vector_hit], "hybrid")),
        ):
            response = self.client.post(
                "/api/courses/python_intro/qa",
                headers=self.headers(teacher),
                json={"question": "变量有什么作用"},
            )

        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertIn("+hybrid", result["mode"])
        self.assertTrue(result["evidence"])
        self.assertTrue(all("scores" in item and "final_score" in item for item in result["evidence"]))

    def test_student_learning_outputs_report_generation_mode(self) -> None:
        student = self.login("student", "Student123!")
        headers = self.headers(student)
        classroom = self.client.get("/api/classrooms", headers=headers).json()[0]
        diagnosis = self.client.get(
            f"/api/classrooms/{classroom['id']}/diagnosis", headers=headers,
        )
        self.assertEqual(diagnosis.status_code, 200, diagnosis.text)
        self.assertEqual(diagnosis.json()["mode"], "offline-rule")
        self.assertTrue(diagnosis.json()["ai_analysis"])

        path = self.client.post(
            f"/api/classrooms/{classroom['id']}/learning-path", headers=headers,
            json={"mastered_node_ids": []},
        )
        self.assertEqual(path.status_code, 200, path.text)
        self.assertEqual(path.json()["mode"], "offline-rule")
        self.assertTrue(path.json()["ai_summary"])

        exercises = self.client.post(
            f"/api/classrooms/{classroom['id']}/exercises", headers=headers,
            json={"question_types": ["基础题", "易错题"], "count": 5},
        )
        self.assertEqual(exercises.status_code, 200, exercises.text)
        self.assertEqual(len(exercises.json()), 5)
        self.assertEqual({item["question_type"] for item in exercises.json()}, {"基础题", "易错题"})
        self.assertTrue(all(item["mode"] == "offline-rule" for item in exercises.json()))


if __name__ == "__main__":
    unittest.main()
