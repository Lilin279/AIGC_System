from __future__ import annotations

import unittest
from unittest.mock import patch

from app.models import KnowledgeEdge, KnowledgeGraph, KnowledgeNode
from app.services import neo4j_adapter
from app.services.recommender import recommend_path_for_course


def _result(columns: list[str], row: list[object]) -> dict:
    return {"columns": columns, "data": [{"row": row}]}


class Neo4jAdapterTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.graph = KnowledgeGraph(
            nodes=[
                KnowledgeNode(id="n1", name="基础"),
                KnowledgeNode(id="n2", name="进阶"),
            ],
            edges=[
                KnowledgeEdge(
                    id="e1", source="n1", target="n2",
                    relation="prerequisite", label="前置关系",
                )
            ],
        )

    def test_sync_is_verified_before_marking_success(self) -> None:
        verification = [
            _result(["node_count"], [2]),
            _result(["edge_count"], [1]),
            _result(["version_id"], ["v3"]),
        ]
        with (
            patch.object(neo4j_adapter, "configured", return_value=True),
            patch.object(neo4j_adapter, "_execute", side_effect=[[], verification]) as execute,
            patch.object(neo4j_adapter, "_record_state") as record,
        ):
            result = neo4j_adapter.sync_confirmed_graph("course", self.graph, "v3")

        self.assertTrue(result["synced"])
        self.assertTrue(result["consistent"])
        self.assertEqual(execute.call_count, 2)
        self.assertEqual(record.call_args_list[0].args[2], "syncing")
        self.assertEqual(record.call_args_list[-1].args[2], "synced")

    def test_sync_mismatch_is_recorded_as_failure(self) -> None:
        verification = [
            _result(["node_count"], [1]),
            _result(["edge_count"], [0]),
            _result(["version_id"], ["v3"]),
        ]
        with (
            patch.object(neo4j_adapter, "configured", return_value=True),
            patch.object(neo4j_adapter, "_execute", side_effect=[[], verification]),
            patch.object(neo4j_adapter, "_record_state") as record,
        ):
            result = neo4j_adapter.sync_confirmed_graph("course", self.graph, "v3")

        self.assertFalse(result["synced"])
        self.assertIn("一致性校验失败", result["message"])
        self.assertEqual(record.call_args_list[-1].args[2], "failed")

    def test_learning_path_uses_neo4j_prerequisites_when_available(self) -> None:
        with patch.object(neo4j_adapter, "prerequisite_edges", return_value=self.graph.edges):
            result = recommend_path_for_course("course", self.graph, ["n1"])

        self.assertEqual(result.mode, "neo4j-rule")
        self.assertEqual([item.node.id for item in result.recommendations], ["n2"])
        self.assertEqual([edge.id for edge in result.path_edges], ["e1"])

    def test_learning_path_falls_back_to_sqlite(self) -> None:
        with patch.object(neo4j_adapter, "prerequisite_edges", return_value=None):
            result = recommend_path_for_course("course", self.graph, ["n1"])

        self.assertEqual(result.mode, "offline-rule")
        self.assertEqual([item.node.id for item in result.recommendations], ["n2"])


if __name__ == "__main__":
    unittest.main()
