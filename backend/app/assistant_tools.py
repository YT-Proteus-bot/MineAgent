"""AI 助手的工具集。

分成两类：
- 读工具：直接执行，结果回填给模型（查画布、查节点说明、读运行日志、查记忆）
- 写工具：不执行，只把「待确认的操作」抛给前端，用户点确认才真正落地

这样 Agent 可以连续推理很多步，但任何会改画布的动作都停在用户手上。
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from . import architectures
from . import assistant_memory as memory
from .db import get_conn
from .node_registry import NODE_INDEX, NODE_TYPES

# 会改画布 / 产生副作用的工具：只生成待确认动作，不直接执行
WRITE_TOOLS = {
    "apply_ops", "apply_canvas", "run_canvas",
    # 项目配置类（都不碰密钥，密钥只能用户自己填）
    "update_service", "update_model", "set_mode", "switch_framework",
    "upsert_provider",
    # 按架构指纹整张生成画布
    "apply_architecture",
}

# 允许 AI 改的对话模型字段（api_key 不在其中，永远由用户填）
MODEL_FIELDS = ("provider", "base_url", "model", "temperature", "max_tokens")


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
    {
        "type": "function",
        "function": {
            "name": "get_config",
            "description": "读取当前画布的配置：框架、推理模式、对话模型（不含密钥）、"
                           "服务设置、以及已配的向量模型/向量库/数据源。改配置前先调它。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_service",
            "description": "修改画布的「服务设置」：入口/会话/并发/可观测/安全。"
                           "按字段深合并，只传要改的部分。生成待用户确认的卡片。",
            "parameters": {
                "type": "object",
                "properties": {
                    "patch": {
                        "type": "object",
                        "description": "要合并进去的服务设置，例如 "
                                       '{"runtime": {"max_concurrency": 8}, '
                                       '"security": {"guardrail": "strict"}}',
                    },
                },
                "required": ["patch"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_model",
            "description": "修改画布的对话模型（provider / base_url / model / temperature / "
                           "max_tokens）。**不能改 API Key**，Key 由用户自己填。"
                           "生成待用户确认的卡片。",
            "parameters": {
                "type": "object",
                "properties": {
                    "provider": {"type": "string"},
                    "base_url": {"type": "string"},
                    "model": {"type": "string"},
                    "temperature": {"type": "number"},
                    "max_tokens": {"type": "integer"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_mode",
            "description": "设置画布的默认推理模式（react / plan_execute / cot / reflexion 等），"
                           "影响新建 agent 节点的默认行为。",
            "parameters": {
                "type": "object",
                "properties": {
                    "mode": {"type": "string", "description": "模式 id，如 react"},
                },
                "required": ["mode"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "switch_framework",
            "description": "切换画布的 Agent 框架（langchain / autogen / crewai / agno / "
                           "smolagents / semantic_kernel / openai_agents / dify）。"
                           "**注意：切换会按新框架重建整张架构图，现有节点和连线会被替换。**"
                           "只在用户明确要求换框架时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "framework": {"type": "string"},
                },
                "required": ["framework"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "upsert_provider",
            "description": "新建或修改一张画布的向量模型 / 向量库 / 数据源配置（非密钥字段）。"
                           "新建时不传 API Key，用户需要自己在画布配置里补 Key。",
            "parameters": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["embedding", "vector", "data"]},
                    "provider": {"type": "string",
                                 "description": "厂商 id，如 openai / qdrant / postgres"},
                    "name": {"type": "string", "description": "实例名，用于节点里引用"},
                    "config": {"type": "object",
                               "description": "非密钥字段，如 base_url / model / collection"},
                    "is_default": {"type": "boolean"},
                },
                "required": ["kind", "provider"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_architectures",
            "description": "列出已收录的开源智能体架构指纹（AutoGPT / MetaGPT / CrewAI 等）。"
                           "用户说「还原 / 复刻 / 按 XX 的架构做」时先查这个，别凭印象画。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_architecture",
            "description": "读某个智能体的架构指纹：核心行为特征、节点拓扑、关键节点代码、"
                           "推荐框架。拿到 behavior 清单才能判断还原是否到位。",
            "parameters": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "指纹 id，如 autogpt / metagpt / crewai"},
                },
                "required": ["id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "apply_architecture",
            "description": "按架构指纹生成一张画布（整张替换当前画布，含关键节点代码）。"
                           "生成待用户确认的卡片。用户要求「还原 XX」且已确认要生成时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "指纹 id"},
                },
                "required": ["id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "scan_source",
            "description": "扫描一个源码库并返回架构线索：目录结构、依赖声明、模块间 import、"
                           "类与函数、prompt 片段、工具定义。"
                           "三个入口任选其一：github_url（公开仓库地址）、"
                           "local_path（本机目录）、source_id（用户已上传的源码包）。"
                           "拿到线索后用 apply_canvas 画出节点图。",
            "parameters": {
                "type": "object",
                "properties": {
                    "github_url": {"type": "string",
                                   "description": "如 https://github.com/owner/repo"},
                    "local_path": {"type": "string", "description": "本机绝对路径"},
                    "source_id": {"type": "string", "description": "上传后拿到的 id"},
                },
                "required": [],
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


def _config(canvas_id: str) -> Dict[str, Any]:
    """当前画布的配置快照（密钥只报有没有，不报值）。"""
    if not canvas_id:
        return {"error": "没有打开画布"}
    with get_conn() as conn:
        row = conn.execute(
            "SELECT framework, mode, model_config, graph FROM canvases WHERE id = ?",
            (canvas_id,)).fetchone()
        if row is None:
            return {"error": "画布不存在"}
        providers = conn.execute(
            "SELECT kind, provider, name, config, is_default FROM providers "
            "WHERE canvas_id = ? ORDER BY kind, created_at", (canvas_id,)).fetchall()

    try:
        model_cfg = json.loads(row["model_config"] or "{}")
    except json.JSONDecodeError:
        model_cfg = {}
    try:
        graph = json.loads(row["graph"] or "{}")
    except json.JSONDecodeError:
        graph = {}

    model = {k: model_cfg.get(k) for k in MODEL_FIELDS if model_cfg.get(k) not in (None, "")}
    model["has_key"] = bool(model_cfg.get("api_key_cipher"))

    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for item in providers:
        try:
            cfg = json.loads(item["config"] or "{}")
        except json.JSONDecodeError:
            cfg = {}
        grouped.setdefault(item["kind"], []).append({
            "name": item["name"],
            "provider": item["provider"],
            "is_default": bool(item["is_default"]),
            "config": cfg,
        })

    return {
        "framework": row["framework"],
        "mode": row["mode"] or "",
        "model": model,
        "service": graph.get("service") or {},
        "providers": grouped,
        "note": "密钥不在返回值里；新建配置后需要用户自己在「画布配置」里补 Key。",
    }


def _scan_source(args: Dict[str, Any]) -> Dict[str, Any]:
    """扫描源码库（GitHub / 本地 / 已上传），返回压缩后的架构线索。"""
    from . import source_fetch, source_scan

    github_url = str(args.get("github_url") or "").strip()
    local_path = str(args.get("local_path") or "").strip()
    source_id = str(args.get("source_id") or "").strip()

    try:
        if github_url:
            source_id = source_fetch.from_github(github_url)
        elif local_path:
            source_id = source_fetch.from_local(local_path)
        elif not source_id:
            return {"error": "需要 github_url / local_path / source_id 三者之一"}
        root = source_fetch.resolve_dir(source_id)
        if not root.is_dir():
            return {"error": f"源码目录不存在：{root}"}
        raw = source_scan.scan(root)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}

    modules = []
    for mod in (raw.get("modules") or [])[:40]:
        item: Dict[str, Any] = {"path": mod.get("path")}
        if mod.get("imports"):
            item["imports"] = mod["imports"][:12]
        if mod.get("classes"):
            item["classes"] = [c[0] if isinstance(c, list) else str(c)
                               for c in mod["classes"][:10]]
        if mod.get("functions"):
            item["functions"] = mod["functions"][:12]
        modules.append(item)

    return {
        "source_id": source_id,
        "file_count": raw.get("file_count"),
        "code_file_count": raw.get("code_file_count"),
        "languages": raw.get("languages"),
        "entrypoints": raw.get("entrypoints"),
        "dependencies": raw.get("dependencies"),
        "tree": "\n".join((raw.get("tree") or "").splitlines()[:60]),
        "modules": modules,
        "prompts": raw.get("prompts"),
        "tool_hints": raw.get("tool_hints"),
        "note": "以上是静态扫描结果。据此推断架构并画节点；不要臆造扫描里没有的模块。",
    }


# --------------------------------------------------------------------------- #
# 统一入口
# --------------------------------------------------------------------------- #
def execute(name: str, args: Dict[str, Any], *, canvas_id: str,
            context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """执行一个工具调用。

    写工具不会真的执行，返回 pending 标记，由调用方转成前端的待确认卡片。
    """
    args = args or {}
    # 按架构指纹生成画布：payload 要带上转好的草稿，不能只回传参数
    if name == "apply_architecture":
        if not canvas_id:
            return {"error": "没有打开画布，无法生成"}
        arch = architectures.get(str(args.get("id") or ""))
        if not arch:
            return {"error": f"没有收录这个架构：{args.get('id')}",
                    "hint": "先调 list_architectures 看有哪些"}
        return {"__pending__": True, "tool": name,
                "payload": {"arch_id": arch["id"], "name": arch["name"],
                            "framework": arch["framework"],
                            "mode": architectures.mode_of(arch),
                            "behavior_count": len(arch["behaviors"]),
                            "draft": architectures.to_draft(arch)}}

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
        if name == "get_config":
            return _config(canvas_id)
        if name == "list_architectures":
            return {"architectures": architectures.list_all(),
                    "note": "没有收录的项目，用 get_node_doc / get_canvas 现场设计，不要编造指纹"}
        if name == "get_architecture":
            arch = architectures.get(str(args.get("id") or ""))
            if not arch:
                return {"error": f"没有收录这个架构：{args.get('id')}",
                        "hint": "先调 list_architectures"}
            return {
                "id": arch["id"],
                "name": arch["name"],
                "framework": arch["framework"],
                "mode": architectures.mode_of(arch),
                "paradigm": arch["paradigm"],
                "summary": arch["summary"],
                "behaviors": arch["behaviors"],
                "nodes": [{k: n.get(k) for k in ("key", "kind", "label")}
                          for n in arch["nodes"]],
                "edges": arch["edges"],
                "notes": arch.get("notes", ""),
            }
        if name == "scan_source":
            return _scan_source(args)
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
