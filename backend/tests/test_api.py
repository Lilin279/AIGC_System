from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path


TEST_DATA = tempfile.TemporaryDirectory()
os.environ["COURSEGRAPH_DATA_DIR"] = str(Path(TEST_DATA.name) / "data")

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

    def test_authentication_and_role_permissions(self) -> None:
        self.assertEqual(self.client.get("/api/courses").status_code, 401)
        student = self.login("student", "Student123!")
        courses = self.client.get("/api/courses", headers=self.headers(student))
        self.assertEqual(courses.status_code, 200)
        self.assertTrue(courses.json())
        forbidden = self.client.post(
            "/api/courses",
            headers=self.headers(student),
            json={"name": "越权课程", "description": "", "status": "draft"},
        )
        self.assertEqual(forbidden.status_code, 403)

    def test_teacher_can_build_and_publish_course(self) -> None:
        teacher = self.login("teacher", "Teacher123!")
        created = self.client.post(
            "/api/courses",
            headers=self.headers(teacher),
            json={"name": "软件工程导论", "description": "P0 测试课程", "status": "draft"},
        )
        self.assertEqual(created.status_code, 201, created.text)
        course_id = created.json()["id"]
        node_ids: list[str] = []
        for name in ("需求分析", "系统设计", "软件测试"):
            response = self.client.post(
                f"/api/courses/{course_id}/graph/nodes",
                headers=self.headers(teacher),
                json={"name": name, "type": "concept", "definition": "", "example": "", "resources": []},
            )
            self.assertEqual(response.status_code, 201, response.text)
            node_ids.append(response.json()["id"])
        edge = self.client.post(
            f"/api/courses/{course_id}/graph/edges",
            headers=self.headers(teacher),
            json={"source": node_ids[0], "target": node_ids[1], "relation": "prerequisite", "label": "前置关系"},
        )
        self.assertEqual(edge.status_code, 201, edge.text)
        published = self.client.put(
            f"/api/courses/{course_id}",
            headers=self.headers(teacher),
            json={"name": "软件工程导论", "description": "P0 测试课程", "status": "published"},
        )
        self.assertEqual(published.status_code, 200, published.text)
        student = self.login("student", "Student123!")
        visible_ids = {item["id"] for item in self.client.get("/api/courses", headers=self.headers(student)).json()}
        self.assertIn(course_id, visible_ids)

    def test_student_progress_is_isolated_by_account(self) -> None:
        first = self.client.post(
            "/api/auth/register",
            json={"username": "student_a", "password": "Password123!", "name": "学生甲", "organization": "测试学校"},
        )
        second = self.client.post(
            "/api/auth/register",
            json={"username": "student_b", "password": "Password123!", "name": "学生乙", "organization": "测试学校"},
        )
        self.assertEqual(first.status_code, 201, first.text)
        self.assertEqual(second.status_code, 201, second.text)
        first_token = first.json()["token"]
        second_token = second.json()["token"]
        graph = self.client.get("/api/courses/python_intro/graph", headers=self.headers(first_token)).json()
        node_id = graph["nodes"][0]["id"]
        marked = self.client.put(
            f"/api/courses/python_intro/progress/{node_id}",
            headers=self.headers(first_token),
            json={"mastered": True},
        )
        self.assertEqual(marked.status_code, 200, marked.text)
        first_graph = self.client.get("/api/courses/python_intro/graph", headers=self.headers(first_token)).json()
        second_graph = self.client.get("/api/courses/python_intro/graph", headers=self.headers(second_token)).json()
        self.assertTrue(next(node for node in first_graph["nodes"] if node["id"] == node_id)["mastered"])
        self.assertFalse(next(node for node in second_graph["nodes"] if node["id"] == node_id)["mastered"])


if __name__ == "__main__":
    unittest.main()
