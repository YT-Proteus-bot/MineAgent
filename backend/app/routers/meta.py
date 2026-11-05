"""元数据：节点类型、框架列表、框架模板图。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..framework_templates import FRAMEWORKS, FRAMEWORK_INDEX, build_graph
from ..node_registry import CATEGORIES, NODE_TYPES

router = APIRouter(prefix="/api/meta", tags=["meta"])


@router.get("")
def meta():
    return {
        "categories": CATEGORIES,
        # 带上 default_code，前端新增节点时可直接生成默认代码
        "nodes": NODE_TYPES,
        "frameworks": FRAMEWORKS,
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
