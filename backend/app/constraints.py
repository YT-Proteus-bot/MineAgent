"""画布编排约束：内置规则库 + 画布级自定义规则。

内置规则是「工业级 Agent 编排」里最容易踩的坑，分三类：
- 结构：入口出口、连通性、孤立节点、环路
- 语义：tool 必须挂在 agent 下游、分支必须有出口
- 数量：节点/连线规模、同类节点数量

自定义规则挂在单张画布上，支持：
- order: 某节点必须在某节点之后 / 之前
- require_kind: 必须出现某类节点
- forbid_kind: 禁止出现某类节点
- max_count: 某类节点最多几个

level = "error" 会拦住保存与运行；"warn" 只提示。
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

AGENT_KINDS = {
    "agent", "worker", "supervisor", "autogen_assistant", "autogen_tool_agent",
    "autogen_group_chat", "crewai_agent", "crewai_crew", "group_chat", "debate",
}
BRANCH_KINDS = {"router", "condition", "loop"}
# 检索类节点是流程里的正常一步，不需要挂到 agent 下游
RETRIEVAL_KINDS = {"rag_retriever", "embedding", "vector_store"}
# 这些节点天然能处理多条入边（汇总/评审类），不算"无法合并"
MULTI_INPUT_OK = {"merge", "critic", "reflector", "evaluator", "self_check",
                  "formatter", "format_observations", "summarize", "output", "blackboard"}
TOOL_KINDS = {
    "tool", "function", "mcp_tool", "crewai_tool", "http_request", "web_search",
    "code_interpreter", "sql_query", "rag_retriever", "file_io", "browser", "shell",
}
ENTRY_KINDS = {"input"}
EXIT_KINDS = {"output"}

BUILTIN_RULES: List[Dict[str, str]] = [
    # ---- 结构 ----
    {"id": "single-input", "label": "有且只有一个输入节点", "level": "error", "category": "结构",
     "desc": "一张画布只能有一个 entry，多个 input 会让执行起点不确定。"},
    {"id": "require-output", "label": "至少有一个输出节点", "level": "error", "category": "结构",
     "desc": "没有 output 就不知道该把什么作为最终答案返回。"},
    {"id": "input-no-incoming", "label": "输入节点不能有入边", "level": "error", "category": "结构",
     "desc": "input 是起点，被别的节点指向会形成环或让入口无法确定。"},
    {"id": "output-no-outgoing", "label": "输出节点不能有出边", "level": "error", "category": "结构",
     "desc": "output 是终点，再往外连会让输出之后还有执行。"},
    {"id": "no-orphan", "label": "不允许孤立节点", "level": "warn", "category": "结构",
     "desc": "既没有入边也没有出边的节点不会被执行，也容易让人误以为它参与了流程。"},
    {"id": "reachable-from-input", "label": "所有节点都能从输入到达", "level": "error", "category": "结构",
     "desc": "从 input 走不到的分支永远不会执行。"},
    {"id": "can-reach-output", "label": "所有节点都能通向输出", "level": "warn", "category": "结构",
     "desc": "走到这些节点后没有路径回到 output，结果可能被丢弃。"},
    {"id": "no-self-loop", "label": "节点不能连自己", "level": "error", "category": "结构",
     "desc": "自环会让执行器在同一节点上无限打转。"},
    {"id": "multi-in-needs-join", "label": "多入边节点应当能合并输入", "level": "warn", "category": "结构",
     "desc": "多个上游直接指向同一节点时，执行器会把它们的输出合并成字典；"
             "如果节点代码只处理字符串，建议中间加一个「分支汇聚」节点。"},
    # ---- 语义 ----
    {"id": "router-two-branches", "label": "分支节点的两条出边都要连", "level": "error", "category": "语义",
     "desc": "router / condition / loop 有多个出口，缺一条时对应分支会直接断掉。"},
    {"id": "loop-has-exit", "label": "循环节点必须有退出出口", "level": "error", "category": "语义",
     "desc": "loop 的 exit 没连，一旦进入循环就退不出来（只能靠 max_visits 兜底）。"},
    {"id": "cycle-needs-control", "label": "有环就必须有循环控制节点", "level": "warn", "category": "语义",
     "desc": "纯数据边构成的环没有任何收敛条件，容易跑满访问次数。"},
    {"id": "tool-under-agent", "label": "工具节点应挂在某个 agent 下游", "level": "warn", "category": "语义",
     "desc": "tool 只有被 agent 当作工具调用时才有意义；直接串在流程里通常不是本意。"},
    {"id": "agent-has-tool", "label": "使用工具的 agent 应当连到 tool", "level": "warn", "category": "语义",
     "desc": "agent 的下游没有 tool 时，它会退化成普通 LLM 调用。"},
    {"id": "skill-has-content", "label": "技能节点必须填 skill.md 内容或文件名", "level": "warn", "category": "语义",
     "desc": "skill 节点为空时运行只会拿到一句占位提示。"},
    {"id": "guardrail-before-shell", "label": "命令执行前建议加护栏", "level": "warn", "category": "语义",
     "desc": "shell / code_interpreter 的上游没有 guardrail 或 human_approval，存在误执行风险。"},
    # ---- 数量 ----
    {"id": "max-nodes", "label": "单画布节点数不超过 200", "level": "warn", "category": "数量",
     "desc": "节点过多会让画布难以维护，考虑拆成子图。"},
]

_RULE_INDEX = {r["id"]: r for r in BUILTIN_RULES}


# --------------------------------------------------------------------------- #
# 图结构辅助
# --------------------------------------------------------------------------- #
class GraphView:
    def __init__(self, graph: Dict[str, Any]):
        self.nodes: List[Dict[str, Any]] = list(graph.get("nodes") or [])
        self.edges: List[Dict[str, Any]] = [
            e for e in (graph.get("edges") or [])
            if e.get("source") and e.get("target")
        ]
        self.kind: Dict[str, str] = {}
        self.label: Dict[str, str] = {}
        self.name: Dict[str, str] = {}
        for n in self.nodes:
            data = n.get("data") or {}
            self.kind[n["id"]] = data.get("kind") or "llm"
            self.label[n["id"]] = data.get("label") or data.get("kind") or n["id"]
            self.name[n["id"]] = data.get("name") or n["id"]
        self.out: Dict[str, List[str]] = defaultdict(list)
        self.inn: Dict[str, List[str]] = defaultdict(list)
        self.out_handles: Dict[str, Set[str]] = defaultdict(set)
        for e in self.edges:
            self.out[e["source"]].append(e["target"])
            self.inn[e["target"]].append(e["source"])
            if e.get("sourceHandle"):
                self.out_handles[e["source"]].add(str(e["sourceHandle"]))

    def ids_of(self, kinds: Iterable[str]) -> List[str]:
        ks = set(kinds)
        return [n["id"] for n in self.nodes if self.kind[n["id"]] in ks]

    def reachable(self, starts: Iterable[str]) -> Set[str]:
        seen: Set[str] = set()
        stack = list(starts)
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            stack.extend(self.out.get(cur, []))
        return seen

    def ancestors(self, node_id: str) -> Set[str]:
        seen: Set[str] = set()
        stack = list(self.inn.get(node_id, []))
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            stack.extend(self.inn.get(cur, []))
        return seen

    def downstream(self, node_id: str) -> Set[str]:
        return self.reachable([node_id]) - {node_id}

    def cycles(self) -> List[List[str]]:
        """返回检测到的环（每个环给一条节点路径）。"""
        color: Dict[str, int] = {}
        stack: List[str] = []
        found: List[List[str]] = []

        def dfs(u: str) -> None:
            color[u] = 1
            stack.append(u)
            for v in self.out.get(u, []):
                if color.get(v, 0) == 0:
                    dfs(v)
                elif color.get(v) == 1:
                    if v in stack:
                        idx = stack.index(v)
                        found.append(stack[idx:] + [v])
                        if len(found) >= 5:
                            return
            stack.pop()
            color[u] = 2

        for nid in self.kind:
            if color.get(nid, 0) == 0:
                dfs(nid)
                if len(found) >= 5:
                    break
        return found

    def describe(self, node_ids: Iterable[str]) -> str:
        names = [self.label.get(i, i) for i in node_ids][:4]
        more = len(list(node_ids)) - len(names)
        text = "、".join(names)
        return text + (f" 等 {more + len(names)} 个" if more > 0 else "")


def _v(rule_id: str, message: str, nodes: Optional[List[str]] = None,
       hint: str = "", level: Optional[str] = None) -> Dict[str, Any]:
    meta = _RULE_INDEX.get(rule_id, {})
    return {
        "rule": rule_id,
        "title": meta.get("label", rule_id),
        "level": level or meta.get("level", "warn"),
        "category": meta.get("category", "自定义"),
        "message": message,
        "hint": hint or meta.get("desc", ""),
        "nodes": nodes or [],
    }


# --------------------------------------------------------------------------- #
# 内置规则
# --------------------------------------------------------------------------- #
def _check_builtin(g: GraphView) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []

    inputs = g.ids_of(ENTRY_KINDS)
    outputs = g.ids_of(EXIT_KINDS)

    if not inputs:
        out.append(_v("single-input", "画布没有输入节点", hint="从右键菜单添加一个「输入 Input」"))
    elif len(inputs) > 1:
        out.append(_v("single-input", f"有 {len(inputs)} 个输入节点：{g.describe(inputs)}",
                      inputs, "只保留一个作为入口"))

    if not outputs:
        out.append(_v("require-output", "画布没有输出节点", hint="从右键菜单添加一个「输出 Output」"))

    for nid in inputs:
        if g.inn.get(nid):
            out.append(_v("input-no-incoming", f"输入节点「{g.label[nid]}」被别的节点指向了", [nid]))
    for nid in outputs:
        if g.out.get(nid):
            out.append(_v("output-no-outgoing", f"输出节点「{g.label[nid]}」还有出边", [nid]))

    for n in g.nodes:
        nid = n["id"]
        if not g.inn.get(nid) and not g.out.get(nid) and g.kind[nid] not in ENTRY_KINDS:
            out.append(_v("no-orphan", f"节点「{g.label[nid]}」没有连任何线", [nid]))

    if inputs:
        reached = g.reachable(inputs)
        unreached = [n["id"] for n in g.nodes if n["id"] not in reached]
        if unreached:
            out.append(_v("reachable-from-input",
                          f"有 {len(unreached)} 个节点从输入走不到：{g.describe(unreached)}", unreached))

    if outputs:
        rev = GraphView({"nodes": g.nodes, "edges": [
            {"source": e["target"], "target": e["source"], "sourceHandle": None} for e in g.edges]})
        can = rev.reachable(outputs)
        dead = [n["id"] for n in g.nodes if n["id"] not in can and g.kind[n["id"]] not in EXIT_KINDS]
        if dead:
            out.append(_v("can-reach-output",
                          f"有 {len(dead)} 个节点走不到输出：{g.describe(dead)}", dead))

    for nid in g.kind:
        if nid in g.out.get(nid, []):
            out.append(_v("no-self-loop", f"节点「{g.label[nid]}」连到了自己", [nid]))

    for nid in g.kind:
        # 循环回边（源节点在我的下游）不算真正的多入边
        back = g.downstream(nid)
        real_ins = [s for s in g.inn.get(nid, []) if s not in back]
        if len(real_ins) > 1 and g.kind[nid] not in {"join"} | MULTI_INPUT_OK:
            out.append(_v("multi-in-needs-join",
                          f"节点「{g.label[nid]}」有 {len(real_ins)} 条入边", [nid]))

    # 分支节点两条出边
    from .node_registry import get_node_type
    for nid in g.kind:
        kind = g.kind[nid]
        if kind not in BRANCH_KINDS:
            continue
        try:
            handles = get_node_type(kind)["outputs"]
        except Exception:
            handles = []
        if len(handles) < 2:
            continue
        missing = [h for h in handles if h not in g.out_handles.get(nid, set())]
        if missing:
            rule = "loop-has-exit" if kind == "loop" else "router-two-branches"
            out.append(_v(rule, f"「{g.label[nid]}」缺少出口：{' / '.join(missing)}", [nid]))

    cycles = g.cycles()
    for cyc in cycles:
        # agent 自己就能决定"继续还是收尾"（ReAct 的循环），也算循环控制
        has_control = any(
            g.kind.get(n) in BRANCH_KINDS or g.kind.get(n) in AGENT_KINDS for n in cyc
        )
        if not has_control:
            out.append(_v("cycle-needs-control",
                          "存在没有任何循环控制节点的环：" + " → ".join(g.label.get(n, n) for n in cyc[:4]),
                          cyc[:6]))

    agents = set(g.ids_of(AGENT_KINDS))
    # planner 也能直接驱动工具（ReWOO 这类"先规划工具序列再执行"的模式）
    drivers = agents | set(g.ids_of({"planner", "decomposer"}))
    for tid in g.ids_of(TOOL_KINDS - RETRIEVAL_KINDS):
        if not (g.ancestors(tid) & drivers):
            out.append(_v("tool-under-agent", f"工具「{g.label[tid]}」不在任何 agent 的下游", [tid]))

    for aid in agents:
        downstream = g.downstream(aid)
        if not any(g.kind.get(x) in TOOL_KINDS for x in downstream):
            out.append(_v("agent-has-tool",
                          f"agent「{g.label[aid]}」下游没有工具节点", [aid], level="info"))

    for n in g.nodes:
        nid = n["id"]
        if g.kind[nid] != "skill":
            continue
        data = n.get("data") or {}
        params = data.get("params") or {}
        code = data.get("code") or ""
        if not (params.get("skill_file") or params.get("skill_text") or "ctx.skill(" in code):
            out.append(_v("skill-has-content", f"技能节点「{g.label[nid]}」还没有内容", [nid]))

    risky = set(g.ids_of({"shell", "code_interpreter"}))
    # 自检 / 条件 / 评审 也能起到"先过一遍"的作用，不只认专门的护栏节点
    guard_kinds = {"guardrail", "human_approval", "self_check", "condition", "critic"}
    for rid in risky:
        guards = {g.kind.get(a) for a in g.ancestors(rid)}
        if not (guards & guard_kinds):
            out.append(_v("guardrail-before-shell", f"「{g.label[rid]}」前没有护栏或人工审批", [rid]))

    if len(g.nodes) > 200:
        out.append(_v("max-nodes", f"画布有 {len(g.nodes)} 个节点，超出建议上限 200"))

    return out


# --------------------------------------------------------------------------- #
# 自定义规则
# --------------------------------------------------------------------------- #
def _check_custom(g: GraphView, rules: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    type_labels = {"order": "顺序约束", "require_kind": "必须包含",
                   "forbid_kind": "禁止出现", "max_count": "数量上限"}
    for r in rules or []:
        rtype = (r.get("type") or "").strip()
        level = "error" if r.get("level") == "error" else "warn"
        rid = f"custom:{r.get('id') or rtype}"
        title = r.get("label") or type_labels.get(rtype, rtype)

        def put(message: str, nodes: Optional[List[str]] = None, hint: str = "") -> None:
            out.append({
                "rule": rid, "title": title, "level": level, "category": "自定义",
                "message": message, "hint": hint or r.get("desc") or "", "nodes": nodes or [],
            })

        if rtype == "order":
            node, anchor = r.get("node"), r.get("anchor")
            if not node or not anchor:
                put("规则缺少节点或参照节点")
                continue
            if node not in g.kind or anchor not in g.kind:
                put(f"规则引用的节点已不存在：{node} / {anchor}")
                continue
            mode = r.get("mode") or "after"
            if mode == "after":
                ok = anchor in g.ancestors(node)
                msg = (f"「{g.label[node]}」必须在「{g.label[anchor]}」之后，"
                       f"但当前没有从后者到前者的路径")
            else:
                ok = node in g.ancestors(anchor)
                msg = (f"「{g.label[node]}」必须在「{g.label[anchor]}」之前，"
                       f"但当前没有从前者到后者的路径")
            if not ok:
                put(msg, [node, anchor])

        elif rtype == "require_kind":
            kind = r.get("kind")
            if kind and not g.ids_of({kind}):
                put(f"画布必须包含「{kind}」类型的节点")

        elif rtype == "forbid_kind":
            kind = r.get("kind")
            found = g.ids_of({kind}) if kind else []
            if found:
                put(f"画布不允许包含「{kind}」类型的节点，当前有 {len(found)} 个", found)

        elif rtype == "max_count":
            kind = r.get("kind")
            limit = int(r.get("count") or 0)
            found = g.ids_of({kind}) if kind else []
            if kind and len(found) > limit:
                put(f"「{kind}」类型节点最多 {limit} 个，当前 {len(found)} 个", found)

    return out


# --------------------------------------------------------------------------- #
# 对外接口
# --------------------------------------------------------------------------- #
def validate(graph: Dict[str, Any], rules: Optional[List[Dict[str, Any]]] = None,
             skip: Optional[Iterable[str]] = None) -> Dict[str, Any]:
    """跑一遍全部约束，返回违规项与统计。"""
    g = GraphView(graph)
    skip_set = set(skip or [])
    violations = [v for v in _check_builtin(g) if v["rule"] not in skip_set]
    violations += [v for v in _check_custom(g, rules or []) if v["rule"] not in skip_set]

    order = {"error": 0, "warn": 1, "info": 2}
    violations.sort(key=lambda v: order.get(v["level"], 9))

    errors = [v for v in violations if v["level"] == "error"]
    warns = [v for v in violations if v["level"] == "warn"]
    infos = [v for v in violations if v["level"] == "info"]
    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warns,
        "infos": infos,
        "violations": violations,
        "counts": {"error": len(errors), "warn": len(warns), "info": len(infos)},
        "node_ids": sorted({n for v in violations for n in v.get("nodes", [])}),
        "checked_rules": len(BUILTIN_RULES) + len(rules or []),
    }


def rule_catalog() -> List[Dict[str, str]]:
    return BUILTIN_RULES


CUSTOM_RULE_TYPES = [
    {"type": "order", "label": "顺序约束", "desc": "某节点必须在另一节点之后 / 之前"},
    {"type": "require_kind", "label": "必须包含", "desc": "画布必须出现某类节点"},
    {"type": "forbid_kind", "label": "禁止出现", "desc": "画布不允许出现某类节点"},
    {"type": "max_count", "label": "数量上限", "desc": "某类节点最多几个"},
]
