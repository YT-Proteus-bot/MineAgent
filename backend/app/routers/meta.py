"""元数据：节点类型、框架列表、框架模板图。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..constraints import CUSTOM_RULE_TYPES, rule_catalog
from ..framework_templates import FRAMEWORKS, FRAMEWORK_INDEX, build_graph
from ..codegen.native import default_block
from ..framework_modes import FRAMEWORK_MODES, all_modes
from ..node_docs import node_doc
from ..node_registry import AGENT_MODES, CATEGORIES, NODE_TYPES

router = APIRouter(prefix="/api/meta", tags=["meta"])


@router.get("")
def meta():
    # 每个节点带上两份代码：
    #   native_code —— agent.py 里的框架原生块（网页「代码逻辑」显示这个）
    #   default_code —— run(ctx) 预览代码（没装框架时 runner 用它降级执行）
    nodes = []
    for n in NODE_TYPES:
        params = {p.get("key"): p.get("default") for p in n.get("params", []) if p.get("key")}
        item = dict(n)
        item["native_code"] = default_block(
            n["kind"], n.get("label", ""), n.get("description", ""), params,
        )
        # 悬停说明：概念 / 解释 / 用途 / 编码建议
        item["doc"] = node_doc(n["kind"], n.get("category", ""))
        nodes.append(item)
    return {
        "categories": CATEGORIES,
        "nodes": nodes,
        "frameworks": FRAMEWORKS,
        "agent_modes": AGENT_MODES,
        # 每个框架支持的模式 + 全量模式清单
        "framework_modes": FRAMEWORK_MODES,
        "all_modes": all_modes(),
        "constraint_rules": rule_catalog(),
        "custom_rule_types": CUSTOM_RULE_TYPES,
        "version": "1.0.0",
    }


@router.get("/nodes/{kind}")
def node_detail(kind: str):
    node = next((n for n in NODE_TYPES if n["kind"] == kind), None)
    if node is None:
        raise HTTPException(404, "节点类型不存在")
    return node


@router.get("/templates/{framework}")
def framework_template(framework: str):
    if framework not in FRAMEWORK_INDEX:
        raise HTTPException(404, "框架不存在")
    return build_graph(framework)
