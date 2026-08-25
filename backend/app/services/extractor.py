from __future__ import annotations

import hashlib
import re
from collections import OrderedDict

from app.models import KnowledgeEdge, KnowledgeGraph, KnowledgeNode
from app.services.parser import clean_sections


RELATION_LABELS = {
    "contains": "包含关系",
    "prerequisite": "前置关系",
    "related": "相关关系",
}

PYTHON_TOPICS = [
    "程序设计", "Python 解释器", "变量", "数据类型", "表达式", "流程控制", "条件语句", "循环语句",
    "函数", "参数传递", "列表", "字典", "字符串处理", "文件读写", "异常处理", "模块", "面向对象",
    "类与对象", "数据可视化", "单元测试", "算法复杂度", "项目实践",
]

DATABASE_TOPICS = [
    "数据库系统", "数据模型", "关系模型", "关系代数", "SQL 查询", "表结构设计", "主键", "外键",
    "实体关系图", "范式", "函数依赖", "事务", "ACID", "并发控制", "锁机制", "索引", "B+树",
    "查询优化", "视图", "存储过程", "数据库安全", "备份恢复",
]


def stable_id(prefix: str, value: str) -> str:
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:10]
    return f"{prefix}_{digest}"


def extract_terms(text: str) -> list[str]:
    candidates: OrderedDict[str, None] = OrderedDict()
    for section in clean_sections(text):
        words = re.findall(r"[\u4e00-\u9fa5A-Za-z0-9_]{2,}", section)
        for word in words:
            if len(word) > 24:
                continue
            if word.lower() in {"markdown", "python", "sql"} or re.search(r"[\u4e00-\u9fa5]", word):
                candidates[word] = None
    return list(candidates.keys())


def build_mock_graph(course_name: str, documents: list[dict]) -> KnowledgeGraph:
    corpus = "\n".join(doc.get("content", "") for doc in documents)
    extracted = extract_terms(corpus)
    defaults = DATABASE_TOPICS if "数据库" in course_name else PYTHON_TOPICS
    topics = list(OrderedDict.fromkeys(extracted + defaults))[:24]

    nodes: list[KnowledgeNode] = []
    for index, topic in enumerate(topics):
        node_type = "chapter" if index in {0, 1, 2} else ("skill" if index % 5 == 0 else "concept")
        nodes.append(
            KnowledgeNode(
                id=stable_id("node", f"{course_name}:{topic}"),
                name=topic,
                type=node_type,
                definition=f"{topic} 是《{course_name}》课程知识体系中的关键知识点，用于支撑后续学习与问答检索。",
                example=f"示例：在学习 {topic} 时，可结合课程资料中的定义、流程或代码片段进行理解。",
                resources=[f"{course_name} 示例资料", "教师上传文档片段"],
            )
        )

    edges: list[KnowledgeEdge] = []
    for index, node in enumerate(nodes[1:], start=1):
        parent = nodes[0 if index < 8 else max(1, index // 4)]
        edges.append(
            KnowledgeEdge(
                id=stable_id("edge", f"contains:{parent.id}:{node.id}"),
                source=parent.id,
                target=node.id,
                relation="contains",
                label=RELATION_LABELS["contains"],
            )
        )
        if index > 1:
            prev = nodes[index - 1]
            edges.append(
                KnowledgeEdge(
                    id=stable_id("edge", f"prerequisite:{prev.id}:{node.id}"),
                    source=prev.id,
                    target=node.id,
                    relation="prerequisite",
                    label=RELATION_LABELS["prerequisite"],
                )
            )
        if index > 3 and index % 3 == 0:
            related = nodes[index - 3]
            edges.append(
                KnowledgeEdge(
                    id=stable_id("edge", f"related:{related.id}:{node.id}"),
                    source=related.id,
                    target=node.id,
                    relation="related",
                    label=RELATION_LABELS["related"],
                )
            )

    return KnowledgeGraph(nodes=nodes, edges=edges)
