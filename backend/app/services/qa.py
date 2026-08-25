from __future__ import annotations

from app.models import KnowledgeGraph, QAResult


def answer_question(graph: KnowledgeGraph, question: str) -> QAResult:
    terms = [token for token in question.replace("？", " ").replace("?", " ").split() if token]
    scored = []
    for node in graph.nodes:
        score = 0
        if node.name in question:
            score += 5
        score += sum(1 for term in terms if term and term in node.definition)
        if score:
            scored.append((score, node))
    if not scored:
        scored = [(1, node) for node in graph.nodes[:3]]
    citations = [node for _, node in sorted(scored, key=lambda item: item[0], reverse=True)[:3]]
    names = "、".join(node.name for node in citations)
    answer = (
        f"根据当前课程知识图谱，问题可以优先关联到 {names}。"
        f"建议先查看这些节点的定义、示例和前置关系，再结合教师上传资料进行复核。"
        "当前为离线演示问答；配置大模型 API 后，可切换为 RAG 生成并返回更完整的引用片段。"
    )
    return QAResult(answer=answer, citations=citations, confidence="offline-rag-demo")
