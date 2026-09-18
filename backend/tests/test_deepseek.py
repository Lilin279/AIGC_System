from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from app.models import KnowledgeNode
from app.services import deepseek


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise deepseek.httpx.HTTPStatusError(
                "request failed", request=deepseek.httpx.Request("POST", "https://example.test"),
                response=deepseek.httpx.Response(self.status_code),
            )


class _FakeClient:
    responses: list[_FakeResponse | Exception] = []

    def __init__(self, *args, **kwargs) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        return None

    def post(self, *args, **kwargs) -> _FakeResponse:
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class DeepSeekContractTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}, clear=False)
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()

    @staticmethod
    def complete_graph_payload() -> str:
        nodes = [
            {
                "name": f"知识点{i}", "type": "concept", "definition": f"知识点{i}的定义", "example": "",
                "sources": [{
                    "document_id": "doc_1", "filename": "chapter.md", "page_no": 2,
                    "excerpt": f"知识点{i}的定义", "confidence": 0.91, "reason": "原文定义",
                }],
            }
            for i in range(1, 21)
        ]
        relations = ["contains", "prerequisite", "related"]
        edges = [
            {
                "source": f"知识点{i}", "target": f"知识点{i + 1}",
                "relation": relations[(i - 1) % 3], "reason": "课程结构关系",
                "sources": [{
                    "document_id": "doc_1", "filename": "chapter.md", "page_no": 2,
                    "excerpt": f"知识点{i}的定义", "confidence": 0.83, "reason": "相邻概念",
                }],
            }
            for i in range(1, 20)
        ]
        return json.dumps({"nodes": nodes, "edges": edges}, ensure_ascii=False)

    def test_structured_extraction_keeps_sources_and_three_relations(self) -> None:
        document = {
            "id": "doc_1", "filename": "chapter.md",
            "content": "[PAGE 2]\n" + "\n".join(f"知识点{i}的定义" for i in range(1, 21)),
        }
        with patch.object(deepseek, "_chat", return_value=self.complete_graph_payload()) as mocked:
            graph = deepseek.extract_graph("编译原理", [document])
        self.assertEqual(mocked.call_count, 1)
        self.assertEqual(len(graph.nodes), 20)
        self.assertEqual({edge.relation for edge in graph.edges}, {"contains", "prerequisite", "related"})
        self.assertEqual(graph.nodes[0].source_refs[0].document_id, "doc_1")
        self.assertEqual(graph.nodes[0].source_refs[0].page_no, 2)

    def test_invalid_json_is_rejected(self) -> None:
        with patch.object(deepseek, "_chat", return_value="not-json"):
            with self.assertRaisesRegex(ValueError, "知识图谱结构不合法"):
                deepseek.extract_graph("测试课", [{"id": "doc_1", "filename": "a.md", "content": "正文"}])

    def test_repair_failure_keeps_initial_graph_and_sources(self) -> None:
        initial = json.loads(self.complete_graph_payload())
        initial["nodes"] = initial["nodes"][:2]
        initial["edges"] = initial["edges"][:1]
        document = {"id": "doc_1", "filename": "chapter.md", "content": "知识点1的定义"}
        for failure in (
            deepseek.DeepSeekTruncatedError("输出被截断"),
            ValueError("DeepSeek 调用失败：timeout"),
            "invalid-json",
            '{"nodes": [{"name": null}]}',
        ):
            with self.subTest(failure=str(failure)):
                warnings: list[str] = []
                with patch.object(deepseek, "_chat", side_effect=[json.dumps(initial), failure]):
                    graph = deepseek.extract_graph("测试课", [document], warnings=warnings)
                self.assertEqual([node.name for node in graph.nodes], ["知识点1", "知识点2"])
                self.assertEqual(len(graph.edges), 1)
                self.assertEqual(graph.nodes[0].source_refs[0].document_id, "doc_1")
                self.assertEqual(graph.nodes[0].source_refs[0].excerpt, "知识点1的定义")
                self.assertIn("已保留首次有效抽取结果", warnings[0])

    def test_incremental_repair_preserves_base_and_references_existing_nodes(self) -> None:
        complete = json.loads(self.complete_graph_payload())
        initial = {"nodes": complete["nodes"][:19], "edges": complete["edges"][:18]}
        duplicate = {**complete["nodes"][0], "definition": "不得覆盖首次定义"}
        addition = {
            "nodes": [duplicate, complete["nodes"][19]],
            "edges": [
                complete["edges"][0], complete["edges"][18],
                {"source": "不存在", "target": "知识点1", "relation": "related"},
                {"source": "知识点1", "target": "知识点1", "relation": "related"},
            ],
        }
        with patch.object(deepseek, "_chat", side_effect=[json.dumps(initial), json.dumps(addition)]):
            graph = deepseek.extract_graph("测试课", [{"id": "doc_1", "content": "知识点1的定义"}])
        self.assertEqual(len(graph.nodes), 20)
        self.assertEqual(len(graph.edges), 19)
        self.assertEqual(graph.nodes[0].definition, "知识点1的定义")
        self.assertTrue(graph.nodes[0].source_refs)
        self.assertEqual(graph.edges[-1].target, graph.nodes[-1].id)

    def test_initial_truncation_does_not_retry_identical_request_and_logs_usage(self) -> None:
        usage = {"prompt_tokens": 2000, "completion_tokens": 12000, "total_tokens": 14000}
        _FakeClient.responses = [_FakeResponse(200, {
            "choices": [{"finish_reason": "length", "message": {"content": '{"nodes":['}}],
            "usage": usage,
        })]
        with (
            patch.object(deepseek.httpx, "Client", _FakeClient),
            patch.object(deepseek, "_record_usage") as record,
        ):
            with self.assertRaises(deepseek.DeepSeekTruncatedError):
                deepseek.extract_graph("测试课", [{"id": "doc_1", "content": "正文"}])
        record.assert_called_once()
        self.assertEqual(record.call_args.args[1:3], ("failed", usage))
        self.assertEqual(_FakeClient.responses, [])

    def test_empty_initial_graph_is_not_presented_as_success(self) -> None:
        with patch.object(deepseek, "_chat", return_value='{"nodes": [], "edges": []}') as chat:
            with self.assertRaisesRegex(ValueError, "未抽取到有效知识点"):
                deepseek.extract_graph("测试课", [{"id": "doc_1", "content": "正文"}])
        chat.assert_called_once()

    def test_chat_retries_429_then_returns_content(self) -> None:
        _FakeClient.responses = [
            _FakeResponse(429, {}),
            _FakeResponse(200, {"choices": [{"finish_reason": "stop", "message": {"content": "ok"}}]}),
        ]
        with patch.object(deepseek.httpx, "Client", _FakeClient), patch.object(deepseek.time, "sleep"):
            result = deepseek._chat({"model": "test"}, attempts=2)
        self.assertEqual(result, "ok")

    def test_chat_retries_5xx_and_timeout(self) -> None:
        success = _FakeResponse(200, {"choices": [{"finish_reason": "stop", "message": {"content": "recovered"}}]})
        for first in (
            _FakeResponse(503, {}),
            deepseek.httpx.ReadTimeout("timeout", request=deepseek.httpx.Request("POST", "https://example.test")),
        ):
            _FakeClient.responses = [first, success]
            with patch.object(deepseek.httpx, "Client", _FakeClient), patch.object(deepseek.time, "sleep"):
                self.assertEqual(deepseek._chat({"model": "test"}, attempts=2), "recovered")

    def test_empty_and_truncated_responses_fail_clearly(self) -> None:
        for payload, message in (
            ({"choices": [{"finish_reason": "stop", "message": {"content": ""}}]}, "返回空内容"),
            ({"choices": [{"finish_reason": "length", "message": {"content": "partial"}}]}, "输出被截断"),
        ):
            _FakeClient.responses = [_FakeResponse(200, payload)]
            with patch.object(deepseek.httpx, "Client", _FakeClient):
                with self.assertRaisesRegex(ValueError, message):
                    deepseek._chat({"model": "test"}, attempts=1)

    def test_offline_exercises_are_labeled(self) -> None:
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": ""}, clear=False):
            result = deepseek.exercises(
                "测试课", [KnowledgeNode(id="n1", name="词法分析", definition="将字符流转换为记号流")], []
            )
        self.assertEqual(result[0].mode, "offline-rule")
        self.assertEqual(result[0].question_type, "基础题")

    def test_offline_exercises_respect_selected_types_and_count(self) -> None:
        nodes = [
            KnowledgeNode(id="n1", name="变量", definition="保存数据"),
            KnowledgeNode(id="n2", name="条件语句", definition="根据条件选择分支"),
        ]
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": ""}, clear=False):
            result = deepseek.exercises("测试课", nodes, [], ["应用题", "易错题"], 5)
        self.assertEqual(len(result), 5)
        self.assertEqual({item.question_type for item in result}, {"应用题", "易错题"})

    def test_learning_analysis_returns_plain_text(self) -> None:
        node = KnowledgeNode(id="n1", name="词法分析", definition="将字符流转换为记号流")
        with patch.object(deepseek, "_chat", return_value="**薄弱原因**\n- 需要复习[1]"):
            result = deepseek.learning_analysis("编译原理", 20, [node], [node], [{"source": "课件", "excerpt": "证据"}])
        self.assertEqual(result, "薄弱原因\n需要复习[1]")

    def test_qa_prompt_combines_course_evidence_with_general_knowledge(self) -> None:
        answer = (
            "**结论：Python 常见变量类型包括 int、float、str 和 bool。**\n"
            "课程图谱：图谱给出变量与数据类型的关系[1]。\n"
            "补充知识：int 表示整数，float 表示小数，str 表示文本，bool 表示真假。"
        )
        with patch.object(deepseek, "_chat", return_value=answer) as chat:
            result = deepseek.answer_with_evidence(
                "Python 有哪些常见变量类型？",
                [
                    {"source": "图谱", "excerpt": "变量 -[相关关系]-> 数据类型"},
                ],
            )
        payload = chat.call_args.args[0]
        system_prompt = payload["messages"][0]["content"]
        self.assertIn("但不是知识上限", system_prompt)
        self.assertIn("自身掌握的稳定、通用学科知识", system_prompt)
        self.assertIn("通用知识放在‘补充知识’部分且不要伪造引用", system_prompt)
        self.assertIn("包含关系不等于前置关系", system_prompt)
        self.assertEqual(result, answer.replace("**", ""))
        self.assertIn("\n补充知识：", result)

    def test_online_qa_can_answer_when_course_evidence_is_empty(self) -> None:
        with patch.object(deepseek, "_chat", return_value="结论：int 是 Python 的整数类型。") as chat:
            result = deepseek.answer_with_evidence("Python 中 int 是什么？", [])
        self.assertIn("int", result)
        self.assertIn("未检索到课程证据", chat.call_args.args[0]["messages"][1]["content"])


if __name__ == "__main__":
    unittest.main()
