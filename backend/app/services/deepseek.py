from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError

from app.models import ExerciseResult, KnowledgeEdge, KnowledgeGraph, KnowledgeNode, SourceReference
from app.services.extractor import RELATION_LABELS, build_mock_graph


PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / ".env", override=False)


class ExtractedSource(BaseModel):
    document_id: str = ""
    filename: str = ""
    page_no: int | None = None
    excerpt: str = ""
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    reason: str = ""


class ExtractedNode(BaseModel):
    name: str
    type: str = "concept"
    definition: str = ""
    example: str = ""
    sources: list[ExtractedSource] = Field(default_factory=list)
    source_excerpt: str = ""


class ExtractedEdge(BaseModel):
    source: str
    target: str
    relation: str
    reason: str = ""
    sources: list[ExtractedSource] = Field(default_factory=list)


class ExtractedGraph(BaseModel):
    nodes: list[ExtractedNode] = Field(default_factory=list)
    edges: list[ExtractedEdge] = Field(default_factory=list)


class GeneratedExercise(BaseModel):
    node_name: str
    question_type: str = "基础题"
    difficulty: str = "基础"
    question: str
    answer: str
    explanation: str
    evidence_ids: list[int] = Field(default_factory=list)


class GeneratedExerciseSet(BaseModel):
    exercises: list[GeneratedExercise] = Field(default_factory=list)


def configured() -> bool:
    return bool(os.environ.get("DEEPSEEK_API_KEY", "").strip())


def model_name() -> str:
    return os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash").strip() or "deepseek-v4-flash"


def extraction_mode() -> str:
    return "deepseek" if configured() else "mock"


def status() -> dict[str, Any]:
    return {
        "provider": "deepseek",
        "configured": configured(),
        "model": model_name(),
        "mode": "deepseek" if configured() else "offline",
        "capabilities": ["graph_extraction", "graphrag_qa", "learning_analysis", "exercise_generation"],
    }


def extract_graph(
    course_name: str, documents: list[dict], warnings: list[str] | None = None,
) -> KnowledgeGraph:
    if not configured():
        return build_mock_graph(course_name, documents)
    corpus = _build_corpus(documents)
    parsed = _request_extracted_graph(course_name, corpus, repair=False)
    if not _to_graph(course_name, parsed, documents).nodes:
        raise ValueError("DeepSeek 未抽取到有效知识点，请检查课件内容后重试")
    if _needs_repair(parsed):
        # 补全是增量操作；可选调用失败不能丢弃首次已通过结构校验的结果。
        try:
            repaired = _request_extracted_graph(
                course_name, corpus, repair=True,
                current=json.dumps({
                    "nodes": [node.name for node in parsed.nodes],
                    "edges": [
                        {"source": edge.source, "target": edge.target, "relation": edge.relation}
                        for edge in parsed.edges
                    ],
                }, ensure_ascii=False, separators=(",", ":")),
            )
            parsed = _merge_extracted_graphs(parsed, repaired)
        except ValueError:
            if warnings is not None:
                warnings.append("自动补全未完成，已保留首次有效抽取结果；请审核数量、关系和来源后再应用")
    return _to_graph(course_name, parsed, documents)


def _merge_extracted_graphs(base: ExtractedGraph, addition: ExtractedGraph) -> ExtractedGraph:
    nodes = list(base.nodes)
    names = {_normalized_name(node.name) for node in nodes}
    for node in addition.nodes:
        key = _normalized_name(node.name)
        if key and key not in names:
            nodes.append(node)
            names.add(key)
    edges = list(base.edges)
    keys = {(_normalized_name(edge.source), _normalized_name(edge.target), edge.relation) for edge in edges}
    for edge in addition.edges:
        source, target = _normalized_name(edge.source), _normalized_name(edge.target)
        key = (source, target, edge.relation)
        if source in names and target in names and source != target and edge.relation in RELATION_LABELS and key not in keys:
            edges.append(edge)
            keys.add(key)
    return ExtractedGraph(nodes=nodes, edges=edges)


def answer_with_evidence(question: str, evidence: list[dict]) -> str:
    if not evidence:
        return "课程资料中没有足够证据回答这个问题。"
    if not configured():
        snippets = "；".join(item["excerpt"][:120] for item in evidence[:3] if item.get("excerpt"))
        return f"根据课程资料，{snippets}" if snippets else "课程资料中没有足够证据回答这个问题。"
    payload = _chat_payload(
        system="你是课程助教。只能依据编号证据回答；证据不足时明确说不知道。引用必须使用[1][2]格式，不得引用未提供的材料。",
        user=f"问题：{question}\n\n证据：\n{_evidence_context(evidence)}",
        max_tokens=1200,
    )
    return _plain_text(_chat(payload, timeout_seconds=12.0, attempts=1, capability="graphrag_qa"))


def learning_analysis(
    course_name: str,
    mastery_rate: float,
    weak_nodes: list[KnowledgeNode],
    recommendations: list[KnowledgeNode],
    evidence: list[dict],
) -> str:
    path_names = "、".join(node.name for node in recommendations[:5]) or "无"
    if not configured():
        return f"当前掌握率为 {mastery_rate}%，建议优先学习：{path_names}。"
    weak_names = "、".join(node.name for node in weak_nodes[:5]) or "无"
    payload = _chat_payload(
        system="你是高校课程学习诊断助手。只依据掌握状态、推荐路径和课程证据给出简洁、可执行的学习建议，不改变系统给出的路径顺序。",
        user=(
            f"课程：{course_name}\n掌握率：{mastery_rate}%\n薄弱知识点：{weak_names}\n"
            f"系统推荐顺序：{path_names}\n证据：\n{_evidence_context(evidence)}\n"
            "请用不超过220字说明薄弱原因、学习顺序和复习方法，并使用[1]格式引用证据。"
        ),
        max_tokens=500,
    )
    return _plain_text(_chat(payload, timeout_seconds=12.0, attempts=1, capability="learning_analysis"))


def exercises(course_name: str, nodes: list[KnowledgeNode], evidence: list[dict]) -> list[ExerciseResult]:
    if not configured():
        return _offline_exercises(nodes, evidence)
    node_names = "、".join(node.name for node in nodes[:5])
    payload = _chat_payload(
        system="只输出合法 json，不要输出 Markdown。题目必须能由给定课程证据作答，不得引入课外事实。",
        user=(
            f"请为《{course_name}》的薄弱知识点生成3道针对性练习，知识点：{node_names}。\n"
            f"证据：\n{_evidence_context(evidence)}\n"
            "题型依次为基础题、应用题、易错题。输出 json："
            '{"exercises":[{"node_name":"","question_type":"基础题","difficulty":"基础",'
            '"question":"","answer":"","explanation":"","evidence_ids":[1]}]}'
        ),
        max_tokens=1800,
        json_output=True,
    )
    try:
        generated = GeneratedExerciseSet.model_validate(json.loads(
            _chat(payload, timeout_seconds=12.0, attempts=1, capability="exercise_generation")
        ))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ValueError("DeepSeek 返回的练习结构不合法") from exc
    node_by_name = {node.name: node for node in nodes}
    fallback_node = nodes[0] if nodes else None
    results: list[ExerciseResult] = []
    for item in generated.exercises[:3]:
        node = node_by_name.get(item.node_name) or fallback_node
        if not node or not item.question.strip() or not item.answer.strip():
            continue
        sources = [evidence[index - 1] for index in item.evidence_ids if 0 < index <= len(evidence)]
        results.append(
            ExerciseResult(
                node_id=node.id, node_name=node.name, question=item.question.strip(), answer=item.answer.strip(),
                explanation=item.explanation.strip(), question_type=item.question_type,
                difficulty=item.difficulty, sources=sources, mode="deepseek-evidence",
            )
        )
    return results or _offline_exercises(nodes, evidence)


def offline_exercises(nodes: list[KnowledgeNode], evidence: list[dict]) -> list[ExerciseResult]:
    return _offline_exercises(nodes, evidence)


def _request_extracted_graph(course_name: str, corpus: str, repair: bool, current: str = "") -> ExtractedGraph:
    task = (
        "已有图谱未达到20个知识点或三类关系。仅返回缺失的节点和关系，不要重复输出已有内容。"
        "补充关系可引用已有知识点名称。总节点数以20个为目标，资料不支持时不要编造。"
        if repair else "请抽取20个有教学价值的知识点并建立关系。"
    )
    payload = _chat_payload(
        system="你是高校课程知识图谱抽取专家。只输出合法 json，不要输出 Markdown。所有实体和关系必须有课程原文依据。",
        user=f"""
课程：《{course_name}》
任务：{task}
要求：
1. 类型使用 chapter/concept/skill/formula/example/project。
2. 关系必须覆盖 contains、prerequisite、related，source/target 使用知识点名称。
3. 每个节点与关系提供一个 sources，包含 document_id、page_no、excerpt、confidence；filename 由系统恢复，无需输出。
4. excerpt 必须从原文直接截取；重复概念合并。
5. definition 不超过50字，example 无需输出，excerpt 不超过40字，关系 reason 不超过20字；关系最多30条。
6. 输出紧凑 json 格式：{{"nodes":[{{"name":"","type":"concept","definition":"","sources":[{{"document_id":"","page_no":1,"excerpt":"","confidence":0.9}}]}}],"edges":[{{"source":"","target":"","relation":"prerequisite","reason":"","sources":[{{"document_id":"","page_no":1,"excerpt":"","confidence":0.9}}]}}]}}

已有输出（仅修复时参考）：
{current}

课程资料：
{corpus}
""".strip(),
        max_tokens=12000,
        json_output=True,
    )
    try:
        raw = _chat(
            payload, timeout_seconds=58.0 if not repair else 35.0, attempts=2 if not repair else 1,
            capability="graph_extraction_repair" if repair else "graph_extraction",
        )
        return ExtractedGraph.model_validate(json.loads(raw))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ValueError("DeepSeek 返回的知识图谱结构不合法") from exc


def _build_corpus(documents: list[dict], max_chars: int = 60000) -> str:
    parts: list[str] = []
    remaining = max_chars
    for document in documents:
        if remaining <= 0:
            break
        content = str(document.get("content", ""))[:remaining]
        remaining -= len(content)
        parts.append(f"### document_id={document.get('id', '')}; filename={document.get('filename', '课程资料')}\n{content}")
    return "\n\n".join(parts)


def _chat_payload(system: str, user: str, max_tokens: int, json_output: bool = False) -> dict:
    payload: dict[str, Any] = {
        "model": model_name(),
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "thinking": {"type": "disabled"},
        "max_tokens": max_tokens,
        "temperature": 0.2,
    }
    if json_output:
        payload["response_format"] = {"type": "json_object"}
    return payload


def _chat(
    payload: dict,
    timeout_seconds: float = 24.0,
    attempts: int = 2,
    capability: str = "general",
) -> str:
    if not configured():
        raise ValueError("未配置 DeepSeek API Key")
    base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
    headers = {"Authorization": f"Bearer {os.environ['DEEPSEEK_API_KEY']}", "Content-Type": "application/json"}
    last_error: Exception | None = None
    started_at = time.perf_counter()
    deadline = started_at + timeout_seconds
    for attempt in range(attempts):
        try:
            remaining = max(1.0, deadline - time.perf_counter())
            request_timeout = min(40.0, remaining) if attempts > 1 else remaining
            with httpx.Client(timeout=httpx.Timeout(request_timeout, connect=min(8.0, request_timeout))) as client:
                response = client.post(f"{base_url}/chat/completions", headers=headers, json=payload)
            if response.status_code == 429 or response.status_code >= 500:
                raise RuntimeError(f"DeepSeek 服务暂时不可用（{response.status_code}）")
            response.raise_for_status()
            response_payload = response.json()
            choice = response_payload["choices"][0]
            if choice.get("finish_reason") == "length":
                error = "DeepSeek 输出被截断（达到输出或上下文长度限制），本次不完整结果未应用"
                _record_usage(capability, "failed", response_payload.get("usage", {}), started_at, error)
                raise DeepSeekTruncatedError(error)
            content = choice["message"]["content"]
            if not content or not content.strip():
                raise ValueError("DeepSeek 返回空内容")
            _record_usage(capability, "success", response_payload.get("usage", {}), started_at)
            return content.strip()
        except DeepSeekTruncatedError:
            # 相同预算重试只会重复消耗 Token；交给抽取层保留已有结果。
            raise
        except (httpx.HTTPError, KeyError, IndexError, RuntimeError, ValueError) as exc:
            last_error = exc
            if attempt + 1 < attempts:
                remaining = deadline - time.perf_counter()
                if remaining <= 1.0:
                    break
                time.sleep(min(0.6 * (2 ** attempt), max(0.0, remaining - 0.5)))
    _record_usage(capability, "failed", {}, started_at, str(last_error or "unknown error"))
    raise ValueError(f"DeepSeek 调用失败：{last_error}")


class DeepSeekTruncatedError(ValueError):
    """模型返回 length 时的非瞬时错误，不按网络故障重试。"""


def _record_usage(
    capability: str,
    status_value: str,
    usage: dict,
    started_at: float,
    error: str = "",
) -> None:
    try:
        from app.database import connect

        with connect() as connection:
            connection.execute(
                """
                INSERT INTO ai_usage_logs(
                  id, provider, model, capability, status, prompt_tokens, completion_tokens,
                  total_tokens, elapsed_ms, error
                ) VALUES (?, 'deepseek', ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"ai_{uuid.uuid4().hex[:16]}", model_name(), capability, status_value,
                    int(usage.get("prompt_tokens", 0) or 0), int(usage.get("completion_tokens", 0) or 0),
                    int(usage.get("total_tokens", 0) or 0), round((time.perf_counter() - started_at) * 1000),
                    error[:500],
                ),
            )
    except Exception:
        pass


def _to_graph(course_name: str, extracted: ExtractedGraph, documents: list[dict]) -> KnowledgeGraph:
    nodes: list[KnowledgeNode] = []
    name_to_id: dict[str, str] = {}
    for item in extracted.nodes:
        name = item.name.strip()
        normalized = _normalized_name(name)
        if not normalized or normalized in name_to_id:
            continue
        node_id = f"node_{uuid.uuid5(uuid.NAMESPACE_URL, f'{course_name}:{normalized}').hex[:12]}"
        name_to_id[normalized] = node_id
        sources = [_source_reference(source, documents) for source in item.sources]
        if not sources and item.source_excerpt:
            sources = [_source_reference(ExtractedSource(excerpt=item.source_excerpt), documents)]
        sources = [source for source in sources if source.excerpt or source.document_id]
        nodes.append(
            KnowledgeNode(
                id=node_id, name=name, type=item.type or "concept", definition=item.definition.strip(),
                example=item.example.strip(), resources=[source.excerpt for source in sources if source.excerpt][:3],
                source_refs=sources[:4],
            )
        )
    edges: list[KnowledgeEdge] = []
    seen: set[tuple[str, str, str]] = set()
    for item in extracted.edges:
        relation = item.relation if item.relation in RELATION_LABELS else "related"
        source = name_to_id.get(_normalized_name(item.source))
        target = name_to_id.get(_normalized_name(item.target))
        key = (source or "", target or "", relation)
        if not source or not target or source == target or key in seen:
            continue
        seen.add(key)
        refs = [_source_reference(ref.model_copy(update={"reason": ref.reason or item.reason}), documents) for ref in item.sources]
        edges.append(
            KnowledgeEdge(
                id=f"edge_{uuid.uuid4().hex[:12]}", source=source, target=target, relation=relation,
                label=RELATION_LABELS[relation], source_refs=[ref for ref in refs if ref.excerpt or ref.document_id][:4],
            )
        )
    return KnowledgeGraph(nodes=nodes, edges=edges)


def _source_reference(source: ExtractedSource, documents: list[dict]) -> SourceReference:
    document = next((doc for doc in documents if doc.get("id") == source.document_id), None)
    if not document and source.filename:
        document = next((doc for doc in documents if doc.get("filename") == source.filename), None)
    if not document and documents:
        document = documents[0]
    excerpt = source.excerpt.strip()[:500]
    content = str(document.get("content", "")) if document else ""
    page_no = source.page_no or _infer_page(content, excerpt)
    confidence = source.confidence if not excerpt or excerpt in content else min(source.confidence, 0.55)
    return SourceReference(
        document_id=str(document.get("id", "")) if document else source.document_id,
        filename=str(document.get("filename", "")) if document else source.filename,
        page_no=page_no, excerpt=excerpt, confidence=confidence, reason=source.reason.strip(),
    )


def _infer_page(content: str, excerpt: str) -> int | None:
    if not content or not excerpt:
        return None
    page_no: int | None = None
    for block in content.split("[PAGE "):
        if "]" in block:
            marker, body = block.split("]", 1)
            if marker.isdigit():
                page_no = int(marker)
            if excerpt in body:
                return page_no
    return None


def _needs_repair(graph: ExtractedGraph) -> bool:
    relations = {edge.relation for edge in graph.edges if edge.relation in RELATION_LABELS}
    return len(graph.nodes) < 20 or len(relations) < 3


def _graph_completeness(graph: ExtractedGraph) -> tuple[int, int, int]:
    relations = {edge.relation for edge in graph.edges if edge.relation in RELATION_LABELS}
    sourced = sum(bool(node.sources or node.source_excerpt) for node in graph.nodes)
    return min(len(graph.nodes), 30), len(relations), sourced


def _evidence_context(evidence: list[dict]) -> str:
    return "\n".join(
        f"[{index + 1}] {item.get('source', '课程资料')}：{item.get('excerpt', '')}"
        for index, item in enumerate(evidence[:8])
    )


def _offline_exercises(nodes: list[KnowledgeNode], evidence: list[dict]) -> list[ExerciseResult]:
    types = [("基础题", "基础"), ("应用题", "中等"), ("易错题", "中等")]
    results: list[ExerciseResult] = []
    for index, node in enumerate(nodes[:3]):
        question_type, difficulty = types[index]
        results.append(
            ExerciseResult(
                node_id=node.id, node_name=node.name,
                question=f"请用自己的话解释“{node.name}”，并给出一个课程内示例。",
                answer=node.definition or f"围绕 {node.name} 的核心定义作答。",
                explanation=node.example or "回答应包含概念定义、适用条件和一个具体例子。",
                question_type=question_type, difficulty=difficulty, sources=evidence[:2], mode="offline-rule",
            )
        )
    return results


def _plain_text(value: str) -> str:
    text = value.replace("**", "").replace("__", "").replace("`", "")
    text = re.sub(r"(?m)^\s*#{1,6}\s*", "", text)
    text = re.sub(r"(?m)^\s*[-*]\s+", "", text)
    return text.strip()


def _normalized_name(name: str) -> str:
    return "".join(name.casefold().split()).replace("-", "").replace("_", "")
