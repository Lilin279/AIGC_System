from __future__ import annotations

from app.models import KnowledgeEdge, KnowledgeGraph, LearningPathItem, LearningPathResult


def recommend_path(
    graph: KnowledgeGraph,
    mastered_node_ids: list[str],
    prerequisite_edges: list[KnowledgeEdge] | None = None,
    mode: str = "offline-rule",
) -> LearningPathResult:
    mastered = set(mastered_node_ids)
    node_by_id = {node.id: node for node in graph.nodes}
    prereq_edges = prerequisite_edges
    if prereq_edges is None:
        prereq_edges = [edge for edge in graph.edges if edge.relation == "prerequisite"]
    incoming: dict[str, list[KnowledgeEdge]] = {}
    outgoing: dict[str, list[KnowledgeEdge]] = {}
    for edge in prereq_edges:
        incoming.setdefault(edge.target, []).append(edge)
        outgoing.setdefault(edge.source, []).append(edge)

    items: list[LearningPathItem] = []
    used_path_edges: list[KnowledgeEdge] = []
    for node in graph.nodes:
        if node.id in mastered:
            continue
        prereqs = incoming.get(node.id, [])
        if prereqs and not all(edge.source in mastered for edge in prereqs):
            continue
        unlocked_count = len([edge for edge in outgoing.get(node.id, []) if edge.target not in mastered])
        priority = 100 + unlocked_count * 10 - len(prereqs)
        reason = "前置知识已满足，可作为下一步学习重点。" if prereqs else "基础入口知识点，适合作为学习起点。"
        items.append(LearningPathItem(node=node, priority=priority, reason=reason))
        used_path_edges.extend(prereqs)

    items.sort(key=lambda item: item.priority, reverse=True)
    return LearningPathResult(recommendations=items[:6], path_edges=used_path_edges, mode=mode)


def recommend_path_for_course(
    course_id: str,
    graph: KnowledgeGraph,
    mastered_node_ids: list[str],
) -> LearningPathResult:
    from app.services.neo4j_adapter import prerequisite_edges

    neo4j_edges = prerequisite_edges(course_id)
    if neo4j_edges is not None:
        return recommend_path(graph, mastered_node_ids, neo4j_edges, "neo4j-rule")
    return recommend_path(graph, mastered_node_ids)
