"""AI 助手的工具集。

分成两类：
- 读工具：直接执行，结果回填给模型（查画布、查节点说明、读运行日志、查记忆）
- 写工具：不执行，只把「待确认的操作」抛给前端，用户点确认才真正落地

这样 Agent 可以连续推理很多步，但任何会改画布的动作都停在用户手上。
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from . import assistant_memory as memory
from .db import get_conn
from .node_registry import NODE_INDEX, NODE_TYPES

# 会改画布 / 产生副作用的工具：只生成待确认动作，不直接执行
WRITE_TOOLS = {"apply_ops", "apply_canvas", "run_canvas"}


def _brief_node(node: Dict[str, Any]) -> Dict[str, Any]:
    data = node.get("data") or {}
    return {
        "id": node.get("id"),
        "kind": data.get("kind"),
        "label": data.get("label"),
        "name": data.get("name"),
        "params": data.get("params") or {},
    }


TOOL_SCHEMAS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_canvas",
            "description": "读取当前画布的完整结构：节点（含 id、类型、参数）和连线。"
                           "要改画布之前先调它拿真实 id。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_node_doc",
            "description": "查某类节点的定义：用途、可用参数及默认值、默认代码。"
                           "不确定某个 kind 能不能用、参数叫什么时先查。",
            "parameters": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "description": "节点类型，如 agent / router / rag_retriever"},
                },
                "required": ["kind"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_node_types",
            "description": "列出可用的节点类型。可按关键词过滤（如「检索」「记忆」）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "过滤关键词，可留空"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_run_log",
            "description": "读最近一次运行的执行过程：每个节点的开始/结束/耗时/输出/报错。"
                           "诊断「为什么跑不起来」时先用它。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_constraints",
            "description": "读当前画布的编排约束检查结果（哪些规则没通过）。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remember",
            "description": "把值得长期记住的事写进这张画布的记忆（约定、踩过的坑、做过的决定）。"
                           "只在用户明确表达偏好/约定，或确认了一个非显然的结论时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "一句话，具体且可复用"},
                    "kind": {"type": "string", "enum": ["note", "preference", "pitfall", "decision"],
                             "description": "记忆类型"},
                },
                "required": ["content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recall",
            "description": "按关键词查这张画布的长期记忆。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "要查什么"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "apply_ops",
            "description": "对当前画布做增量修改（增删节点、改参数/代码、连线、挪位置）。"
                           "调用后不会立刻生效，会生成一张待用户确认的卡片。",
            "parameters": {
                "type": "object",
                "properties": {
                    "operations": {
                        "type": "array",
                        "description": "操作数组，每条一个对象",
                        "items": {
                            "type": "object",
                            "properties": {
                                "op": {"type": "string",
                                       "enum": ["add_node", "remove_node", "update_node",
                                                "set_code", "connect", "disconnect",
                                                "move_node", "relayout"]},
                                "id": {"type": "string"},
                                "key": {"type": "string"},
                                "kind": {"type": "string"},
                                "label": {"type": "string"},
                                "name": {"type": "string"},
                                "params": {"type": "object"},
                                "code": {"type": "string"},
                                "source": {"type": "string"},
                                "target": {"type": "string"},
                                "branch": {"type": "string"},
                                "x": {"type": "number"},
                                "y": {"type": "number"},
                            },
                            "required": ["op"],
                        },
                    },
                },
                "required": ["operations"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "apply_canvas",
            "description": "用一张完整的新画布替换当前画布（节点 + 连线）。"
                           "适合「重新设计 / 换成某某架构」这类整体重做；局部改动请用 apply_ops。",
            "parameters": {
                "type": "object",
                "properties": {
                    "nodes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "key": {"type": "string"},
                                "kind": {"type": "string"},
                                "label": {"type": "string"},
                                "name": {"type": "string"},
                                "params": {"type": "object"},
                                "code": {"type": "string"},
                            },
                            "required": ["kind"],
                        },
                    },
                    "edges": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "source": {"type": "string"},
                                "target": {"type": "string"},
                                "branch": {"type": "string"},
                            },
                            "required": ["source", "target"],
                        },
                    },
                },
                "required": ["nodes"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_canvas",
            "description": "运行当前画布并返回执行结果。会真的消耗模型额度，"
                           "只在用户明确要求运行/验证时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "input": {"type": "string", "description": "传给画布的输入"},
                },
                "required": ["input"],
            },
        },
    },
]


# --------------------------------------------------------------------------- #
# 读工具
# --------------------------------------------------------------------------- #
def _read_canvas(canvas_id: str) -> Dict[str, Any]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT graph, framework FROM canvases WHERE id = ?", (canvas_id,)).fetchone()
    if row is None:
        return {"error": "画布不存在"}
    try:
        graph = json.loads(row["graph"] or "{}")
    except json.JSONDecodeError:
        graph = {}
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    return {
        "framework": row["framework"],
        "node_count": len(nodes),
        "nodes": [_brief_node(n) for n in nodes],
        "edges": [{"source": e.get("source"), "target": e.get("target"),
                   "branch": e.get("sourceHandle") or ""} for e in edges],
    }


def _node_doc(kind: str) -> Dict[str, Any]:
    meta = NODE_INDEX.get(kind)
    if not meta:
        return {"error": f"没有这个节点类型：{kind}",
                "hint": "先调 list_node_types 看可用类型"}
    return {
        "kind": kind,
        "label": meta.get("label"),
        "description": meta.get("description"),
        "category": meta.get("category"),
        "params": [{k: p.get(k) for k in ("key", "label", "default", "options")}
                   for p in (meta.get("params") or [])],
        "default_code": (meta.get("default_code") or "")[:1200],
    }


def _list_types(keyword: str = "") -> Dict[str, Any]:
    kw = (keyword or "").strip()
    items = []
    for node in NODE_TYPES:
        text = f"{node.get('kind')} {node.get('label')} {node.get('description') or ''}"
        if kw and kw not in text:
            continue
        items.append({"kind": node.get("kind"), "label": node.get("label")})
    return {"count": len(items), "types": items[:80]}


def _run_log(context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    ctx = context or {}
    log = ctx.get("run_log") or []
    return {
        "last_error": ctx.get("last_run") or "",
        "events": log[-80:],
        "note": "" if log else "前端没有带运行日志（用户可能关了上下文或还没运行过）",
    }


def _constraints(context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    return {"violations": (context or {}).get("violations") or []}


# --------------------------------------------------------------------------- #
# 统一入口
# --------------------------------------------------------------------------- #
def execute(name: str, args: Dict[str, Any], *, canvas_id: str,
            context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """执行一个工具调用。

    写工具不会真的执行，返回 pending 标记，由调用方转成前端的待确认卡片。
    """
    args = args or {}
    if name in WRITE_TOOLS:
        if not canvas_id:
            return {"error": "没有打开画布，无法执行修改"}
        return {"__pending__": True, "tool": name, "payload": args}

    try:
        if name == "get_canvas":
            return _read_canvas(canvas_id)
        if name == "get_node_doc":
            return _node_doc(str(args.get("kind") or ""))
        if name == "list_node_types":
            return _list_types(str(args.get("keyword") or ""))
        if name == "get_run_log":
            return _run_log(context)
        if name == "get_constraints":
            return _constraints(context)
        if name == "remember":
            if not canvas_id:
                return {"error": "没有打开画布，无法写记忆"}
            return memory.add(canvas_id, str(args.get("content") or ""),
                              str(args.get("kind") or "note"))
        if name == "recall":
            if not canvas_id:
                return {"error": "没有打开画布"}
            items = memory.search(canvas_id, str(args.get("query") or ""), limit=6)
            return {"count": len(items),
                    "memories": [{"kind": m.get("kind"), "content": m.get("content")}
                                 for m in items]}
        return {"error": f"未知工具：{name}"}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}
