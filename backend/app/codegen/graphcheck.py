"""生成结果自检：在把 agent.py 交给用户之前，先把「静默出错」的那类问题找出来。

检查的都是图结构层面的硬伤：
- 节点没有入边（画布上删了边、或者生成的边和画布不一致）；
- 节点从 input 走不到（孤岛，运行时会跳过它）；
- 条件边的分支名对不上连线的 handle；
- agent 还在用全局 TOOLS（工具没有按下游收敛）。

只做静态解析，不依赖 langchain / langgraph，可以在生成时同步跑。
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Set, Tuple

ADD_EDGE = re.compile(
    r'builder\.add_edge\(\s*(START|END|"([^"]+)")\s*,\s*(END|"([^"]+)")\s*\)'
)
COND = re.compile(
    r'builder\.add_conditional_edges\(\s*(?:\n\s*)?"([^"]+)",\s*(?:\n\s*)?.*?\{(.*?)\}\s*,?\s*(?:\n\s*)?\)',
    re.S,
)
MAP_ENTRY = re.compile(r'"([^"]+)"\s*:\s*(END|"([^"]+)")')


def _node_name(token: str) -> str:
    token = (token or "").strip()
    if token == "START":
        return "__start__"
    return token.strip('"')


def parse_graph(code: str) -> Tuple[Dict[str, Set[str]], List[str]]:
    """从生成的代码里还原出边表，返回 (出边表, 解析问题)。"""
    outs: Dict[str, Set[str]] = {}
    issues: List[str] = []

    for m in ADD_EDGE.finditer(code):
        src = _node_name(m.group(1))
        dst = None if m.group(3) == "END" else (m.group(4) or m.group(3))
        outs.setdefault(src, set())
        if dst:
            outs[src].add(dst)

    for m in COND.finditer(code):
        src, body = m.group(1), m.group(2)
        targets = [e.group(3) or e.group(2) for e in MAP_ENTRY.finditer(body)]
        if not targets:
            issues.append(f"条件边 {src} 没有解析出目标")
            continue
        outs.setdefault(src, set()).update(t for t in targets if t and t != "END")

    return outs, issues


def check_code(spec: Dict[str, Any], code: str, blocks: Dict[str, str],
               tool_kinds: Set[str], agent_kinds: Set[str], kind_of) -> List[str]:
    """对着生成的 agent.py 做结构自检，返回问题列表（空表示通过）。"""
    if "StateGraph(" not in code:
        # 不是 LangGraph 图（AutoGen / CrewAI / SmolAgents 各有自己的组织方式），没有「边」可查
        return []
    issues: List[str] = []
    outs, parse_issues = parse_graph(code)
    issues += parse_issues

    graph_nodes = [n for n in spec["nodes"] if kind_of(n) not in tool_kinds]
    by_name = {n["name"]: n for n in graph_nodes}
    incoming = {t for targets in outs.values() for t in targets}
    has_cond = "add_conditional_edges" in code
    has_err_edge = any(str(e.get("sourceHandle") or "") == "error" for e in spec.get("edges", []))

    for n in graph_nodes:
        if kind_of(n) == "input":
            continue
        if n["name"] in incoming:
            continue
        if has_err_edge and has_cond:
            continue  # 正常边可能全部走条件边，静态判断不了，放行
        issues.append(f"节点「{n.get('label') or n['name']}」({n['name']}) 没有入边，运行时会被跳过")

    start = next((n["name"] for n in graph_nodes if kind_of(n) == "input"), None)
    if start:
        seen = {start}
        stack = [start]
        while stack:
            cur = stack.pop()
            for nxt in outs.get(cur, ()):
                if nxt in by_name and nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        for n in graph_nodes:
            if n["name"] not in seen:
                issues.append(f"节点「{n.get('label') or n['name']}」从 input 走不到（不可达）")

    for n in graph_nodes:
        if kind_of(n) not in agent_kinds:
            continue
        block = blocks.get(n["id"], "")
        if "tools=TOOLS," in block or "tools=TOOLS\n" in block:
            issues.append(f"agent「{n['name']}」还在用全局 TOOLS，工具没有按下游收敛")
        elif block and "TOOLS_" not in block:
            issues.append(f"agent「{n['name']}」没有生成自己的工具列表")

    return issues
