"""Agent 框架定义 + 各框架的默认架构图模板。"""
from __future__ import annotations

from typing import Any, Dict, List

from .node_registry import get_node_type

FRAMEWORKS: List[Dict[str, Any]] = [
    {
        "id": "langchain",
        "label": "LangChain / LangGraph",
        "runnable": True,
        "badge": "可运行",
        "color": "#1c8f6f",
        "description": "以 StateGraph 组织的状态机式 Agent，最适合把画布 1:1 映射成可执行代码。",
        "requires": "langgraph>=0.2.0",
    },
    {
        "id": "autogen",
        "label": "AutoGen",
        "runnable": True,
        "badge": "可运行",
        "color": "#2563eb",
        "description": "微软多智能体对话框架，画布节点映射为 AssistantAgent / GroupChat。",
        "requires": "autogen-agentchat>=0.4.0",
    },
    {
        "id": "crewai",
        "label": "CrewAI",
        "runnable": True,
        "badge": "可运行",
        "color": "#c2410c",
        "description": "角色扮演式多智能体协作，画布节点映射为 Agent / Task / Crew。",
        "requires": "crewai>=0.60.0",
    },
    {
        "id": "metagpt",
        "label": "MetaGPT",
        "runnable": False,
        "badge": "架构图",
        "color": "#6d28d9",
        "description": "软件公司式 SOP 多智能体（产品经理 / 架构师 / 工程师）。",
        "requires": "metagpt",
    },
    {
        "id": "agno",
        "label": "Agno",
        "runnable": False,
        "badge": "架构图",
        "color": "#be123c",
        "description": "轻量高性能 Agent 框架，Team + Memory + Knowledge 组合。",
        "requires": "agno",
    },
    {
        "id": "smolagents",
        "label": "SmolAgents",
        "runnable": False,
        "badge": "架构图",
        "color": "#0e7490",
        "description": "HuggingFace 的代码型 Agent，用 CodeAgent 生成并执行代码。",
        "requires": "smolagents",
    },
    {
        "id": "semantic_kernel",
        "label": "Semantic Kernel",
        "runnable": False,
        "badge": "架构图",
        "color": "#4338ca",
        "description": "微软的企业级 SDK，Plugin + Planner + Function 调用。",
        "requires": "semantic-kernel",
    },
    {
        "id": "openai_agents",
        "label": "OpenAI Agents SDK",
        "runnable": False,
        "badge": "架构图",
        "color": "#111827",
        "description": "Agent + Handoff + Guardrail + Session 四件套。",
        "requires": "openai-agents",
    },
    {
        "id": "dify",
        "label": "Dify Workflow",
        "runnable": False,
        "badge": "架构图",
        "color": "#0369a1",
        "description": "可视化工作流风格：开始 → 节点链 → 条件分支 → 结束。",
        "requires": "dify",
    },
    {
        "id": "custom",
        "label": "空白画布",
        "runnable": False,
        "badge": "自定义",
        "color": "#64748b",
        "description": "只放输入/输出两个方块，节点自己拖。",
        "requires": "",
    },
]

FRAMEWORK_INDEX = {f["id"]: f for f in FRAMEWORKS}
RUNNABLE = {"langchain", "autogen", "crewai"}


def _mk(kind: str, idx: int, label: str | None = None, params: Dict[str, Any] | None = None,
        name: str | None = None) -> Dict[str, Any]:
    meta = get_node_type(kind)
    node_name = name or f"{kind}_{idx}"
    return {
        "id": f"n{idx}",
        "type": "agent",
        "position": {"x": 0, "y": 0},
        "data": {
            "kind": kind,
            "label": label or meta["label"],
            "name": node_name,
            "description": meta["description"],
            "code": meta["default_code"],
            "language": meta["language"],
            "params": dict(params or {}),
            "status": "idle",
        },
    }


def _edge(src: str, dst: str, src_handle: str | None = None, label: str | None = None) -> Dict[str, Any]:
    eid = f"e{src}__{dst}" + (f"__{src_handle}" if src_handle else "")
    return {
        "id": eid,
        "source": src,
        "target": dst,
        "sourceHandle": src_handle,
        "targetHandle": "in",
        "label": label,
        "data": {},
    }


def _langchain() -> tuple[list, list]:
    nodes = [
        _mk("input", 1),
        _mk("planner", 2),
        _mk("agent", 3, "Agent（ReAct）", {"max_steps": 6}),
        _mk("tool", 4, "工具：search", {"name": "search", "query": ""}, name="search_tool"),
        _mk("observation", 5),
        _mk("review_observation", 6),
        _mk("router", 7, "继续 or 收敛", {"question": "观察是否已足够回答用户问题？"}),
        _mk("format_observations", 8),
        _mk("formatter", 9),
        _mk("output", 10),
    ]
    edges = [
        _edge("n1", "n2"),
        _edge("n2", "n3"),
        _edge("n3", "n4", None, "调用工具"),
        _edge("n4", "n5"),
        _edge("n5", "n6"),
        _edge("n6", "n7"),
        _edge("n7", "n3", "true", "继续循环"),
        _edge("n7", "n8", "false", "已收敛"),
        _edge("n8", "n9"),
        _edge("n9", "n10"),
    ]
    return nodes, edges


def _autogen() -> tuple[list, list]:
    nodes = [
        _mk("input", 1),
        _mk("autogen_user_proxy", 2, "UserProxy（执行器）", {"agent_name": "user_proxy"}),
        _mk("autogen_assistant", 3, "Planner", {"agent_name": "planner", "system_message": "你负责任务规划。"}),
        _mk("autogen_assistant", 4, "Coder", {"agent_name": "coder", "system_message": "你负责写代码。"}),
        _mk("autogen_assistant", 5, "Reviewer", {"agent_name": "reviewer", "system_message": "你负责评审质量。"}),
        _mk("autogen_group_chat", 6, "GroupChat", {"agents": ["planner", "coder", "reviewer"], "max_round": 6}),
        _mk("tool", 7, "工具：code_exec", {"name": "code_exec"}, name="code_exec_tool"),
        _mk("observation", 8),
        _mk("formatter", 9),
        _mk("output", 10),
    ]
    edges = [
        _edge("n1", "n2"),
        _edge("n2", "n6"),
        _edge("n3", "n6"),
        _edge("n4", "n6"),
        _edge("n5", "n6"),
        _edge("n6", "n7"),
        _edge("n7", "n8"),
        _edge("n8", "n9"),
        _edge("n9", "n10"),
    ]
    return nodes, edges


def _crewai() -> tuple[list, list]:
    nodes = [
        _mk("input", 1),
        _mk("crewai_agent", 2, "Researcher", {"role": "研究员", "goal": "收集并验证事实"}),
        _mk("crewai_tool", 3, "Search Tool", {"name": "search"}),
        _mk("crewai_task", 4, "研究任务", {"description": "检索并整理资料", "expected_output": "资料卡片"}),
        _mk("crewai_agent", 5, "Writer", {"role": "撰稿人", "goal": "输出结构化报告"}),
        _mk("crewai_task", 6, "写作任务", {"description": "基于资料写报告", "expected_output": "Markdown 报告"}),
        _mk("crewai_crew", 7, "Crew", {"process": "sequential"}),
        _mk("output", 8),
    ]
    edges = [
        _edge("n1", "n2"),
        _edge("n3", "n2", None, "工具"),
        _edge("n2", "n4"),
        _edge("n4", "n5"),
        _edge("n5", "n6"),
        _edge("n6", "n7"),
        _edge("n7", "n8"),
    ]
    return nodes, edges


def _generic(fw: Dict[str, Any]) -> tuple[list, list]:
    """非可运行框架的通用架构图：主管 + 双 worker + 工具 + 观察 + 交付。"""
    nodes = [
        _mk("input", 1),
        _mk("planner", 2, f"{fw['label']} · 规划器"),
        _mk("supervisor", 3, "主管 Supervisor"),
        _mk("worker", 4, "Worker A", {"role": "执行者"}),
        _mk("tool", 5, "工具：search", {"name": "search"}, name="search_tool"),
        _mk("worker", 6, "Worker B", {"role": "校验者"}),
        _mk("observation", 7),
        _mk("review_observation", 8),
        _mk("formatter", 9),
        _mk("output", 10),
    ]
    edges = [
        _edge("n1", "n2"),
        _edge("n2", "n3"),
        _edge("n3", "n4"),
        _edge("n5", "n4"),
        _edge("n4", "n6"),
        _edge("n6", "n7"),
        _edge("n7", "n8"),
        _edge("n8", "n9"),
        _edge("n9", "n10"),
    ]
    return nodes, edges


def _dify() -> tuple[list, list]:
    nodes = [
        _mk("input", 1, "开始"),
        _mk("prompt", 2, "提示词编排"),
        _mk("llm", 3, "LLM 节点"),
        _mk("condition", 4, "知识检索分支", {"expr": "len(ctx.text) > 0"}),
        _mk("rag_retriever", 5, "知识检索"),
        _mk("formatter", 6, "变量聚合"),
        _mk("output", 7, "结束"),
    ]
    edges = [
        _edge("n1", "n2"),
        _edge("n2", "n3"),
        _edge("n3", "n4"),
        _edge("n4", "n5", "true", "需要检索"),
        _edge("n5", "n6"),
        _edge("n4", "n6", "false", "直接回答"),
        _edge("n6", "n7"),
    ]
    return nodes, edges


def _custom() -> tuple[list, list]:
    nodes = [_mk("input", 1), _mk("llm", 2), _mk("output", 3)]
    edges = [_edge("n1", "n2"), _edge("n2", "n3")]
    return nodes, edges


_BUILDERS = {
    "langchain": _langchain,
    "autogen": _autogen,
    "crewai": _crewai,
    "dify": _dify,
    "custom": _custom,
}


def auto_layout(nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """按有向图层级自动排布，横向是流程方向。"""
    ids = [n["id"] for n in nodes]
    if not ids:
        return nodes
    succ: Dict[str, List[str]] = {i: [] for i in ids}
    indeg: Dict[str, int] = {i: 0 for i in ids}
    for e in edges:
        s, t = e["source"], e["target"]
        if s in succ and t in indeg:
            succ[s].append(t)
            indeg[t] += 1

    layer: Dict[str, int] = {}
    roots = [i for i in ids if indeg[i] == 0] or ids[:1]
    queue = list(roots)
    for r in roots:
        layer[r] = 0
    guard = 0
    while queue and guard < 10000:
        guard += 1
        cur = queue.pop(0)
        for nxt in succ[cur]:
            nl = layer[cur] + 1
            if nxt not in layer or layer[nxt] < nl:
                if nxt not in layer:
                    queue.append(nxt)
                layer[nxt] = nl
    for i in ids:
        layer.setdefault(i, 0)

    buckets: Dict[int, List[str]] = {}
    for i in ids:
        buckets.setdefault(layer[i], []).append(i)

    xs = {i: 0.0 for i in ids}
    ys = {i: 0.0 for i in ids}
    for lv, members in buckets.items():
        for idx, nid in enumerate(members):
            xs[nid] = 60.0 + lv * 296.0
            ys[nid] = 60.0 + idx * 178.0
    for n in nodes:
        n["position"] = {"x": xs[n["id"]], "y": ys[n["id"]]}
    return nodes


def build_graph(framework: str) -> Dict[str, Any]:
    fw = FRAMEWORK_INDEX.get(framework) or FRAMEWORK_INDEX["custom"]
    builder = _BUILDERS.get(fw["id"])
    nodes, edges = builder() if builder else _generic(fw)
    nodes = auto_layout(nodes, edges)
    return {"nodes": nodes, "edges": edges, "viewport": {"x": 0, "y": 0, "zoom": 0.85}}
