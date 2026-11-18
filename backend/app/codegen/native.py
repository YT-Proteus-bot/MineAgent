"""把画布编译成一份真正的框架原生代码（agent.py）。

设计原则：**代码是主体，画布节点是它的视图**。
每个节点对应 agent.py 里一个带 ═══ 标记的代码块，块里是这个节点真正的框架写法
（@tool / create_react_agent / ChatPromptTemplate + llm.invoke …），而不是对某个
通用执行器的调用。生成结果应该一眼能看出这是一个标准 LangGraph / AutoGen / CrewAI 项目。
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

from ..tool_presets import TOOL_PRESETS

ROUTE_KINDS = {"router", "condition", "branch", "switch"}
# 这些框架没有专属 codegen，统一生成 LangGraph/StateGraph 代码（header 也是 LangChain）
_LANGGRAPH_FRAMEWORKS = {
    "langchain", "langgraph", "custom", "dify", "metagpt",
}

TOOL_KINDS = {
    "tool", "function", "mcp_tool", "crewai_tool", "http_request", "web_search",
    "code_interpreter", "sql_query", "rag_retriever", "file_io", "browser", "shell",
}
AGENT_KINDS = {
    "agent", "worker", "supervisor", "autogen_assistant", "crewai_agent",
    "group_chat", "debate",
}
LLM_KINDS = {
    "llm", "planner", "observation", "review_observation", "reflect", "critique",
    "formatter", "format_observations", "summarize", "classify", "extract",
    "translate", "rewrite", "judge", "evaluator", "writer", "researcher",
}

BLOCK_BEGIN = "# ═══════════════════════════════════════════════════════════════"
BLOCK_END = "# ═══════════════════════════════════════════════════════════════"


def _q(text: str) -> str:
    """安全地生成 Python 字符串字面量。"""
    return json.dumps(text or "", ensure_ascii=False)


def _ascii_id(text: str, fallback: str = "agent") -> str:
    """只保留 ASCII 字母数字和 `_` / `-`。

    有些框架（如 Semantic Kernel）要求 agent 名匹配 `^[0-9A-Za-z_-]+$`，
    中文节点名会直接校验失败，所以生成时统一转一下。
    """
    out = []
    for ch in str(text or ""):
        out.append(ch if (ch.isascii() and (ch.isalnum() or ch in "_-")) else "_")
    ident = "".join(out).strip("_-")
    return (ident or fallback)[:48]


def _pyid(name: str) -> str:
    out = []
    for ch in name or "":
        if ch.isalnum() or ch == "_":
            out.append(ch)
        else:
            out.append("_")
    ident = "".join(out).strip("_") or "node"
    if ident[0].isdigit():
        ident = "n_" + ident
    return ident


def _kind_of(node: Dict[str, Any]) -> str:
    return (node.get("kind") or "llm").lower()


def _key_env(node_id: str) -> str:
    """节点级 key 的环境变量名，必须和运行时注入的名字一致。"""
    safe = "".join(ch if ch.isalnum() else "_" for ch in (node_id or "")).upper()[:40]
    return f"MINEAGENT_KEY_{safe or 'NODE'}"


def _has_own_model(node: Dict[str, Any]) -> bool:
    m = node.get("model") or {}
    return bool(m.get("model") or m.get("base_url"))


def _llm_var(node: Dict[str, Any]) -> str:
    """节点用到模型时用哪个变量：有独立模型就用节点的，否则用全局 llm。"""
    return f"{_pyid(node['name']).upper()}_LLM" if _has_own_model(node) else "llm"


def _llm_decl(node: Dict[str, Any]) -> str:
    """节点配了独立模型时，生成它的 ChatOpenAI 实例。"""
    if not _has_own_model(node):
        return ""
    m = node.get("model") or {}
    var = _llm_var(node)
    model_expr = _q(m["model"]) if m.get("model") else 'CFG.get("model", "deepseek-chat")'
    base_expr = (
        _q(m["base_url"]) if m.get("base_url")
        else 'os.environ.get("MINEAGENT_BASE_URL") or CFG.get("base_url")'
    )
    env = _key_env(node["id"])
    temp = m.get("temperature")
    temp_expr = f"{float(temp)}" if isinstance(temp, (int, float)) else 'CFG.get("temperature", 0.3)'
    return (
        f"# ⚙ 这个节点在网页上配了独立模型\n"
        f"{var} = ChatOpenAI(\n"
        f"    model={model_expr},\n"
        f"    base_url={base_expr},\n"
        f'    api_key=os.environ.get("{env}") or os.environ.get("MINEAGENT_API_KEY") or "EMPTY",\n'
        f"    temperature={temp_expr},\n"
        f"    timeout=float(os.environ.get(\"MINEAGENT_LLM_TIMEOUT\") or 120),\n"
        f"    callbacks=[_USAGE_HANDLER],\n"
        f")\n"
    )


def _params(node: Dict[str, Any]) -> Dict[str, Any]:
    return node.get("params") or {}


def _num(params: Dict[str, Any], key: str, default: float) -> float:
    try:
        return float(params.get(key, default))
    except (TypeError, ValueError):
        return default


def _text(params: Dict[str, Any], key: str, default: str = "") -> str:
    value = params.get(key, default)
    return str(value) if value is not None else default


def topo_order(spec: Dict[str, Any]) -> List[str]:
    """按拓扑序返回节点 id（找不到入环的先按原顺序补在后面）。"""
    ids = [n["id"] for n in spec["nodes"]]
    kind = {n["id"]: _kind_of(n) for n in spec["nodes"]}
    succ: Dict[str, List[str]] = {i: [] for i in ids}
    indeg: Dict[str, int] = {i: 0 for i in ids}
    for e in spec["edges"]:
        s, t = e.get("source"), e.get("target")
        if s in succ and t in indeg:
            succ[s].append(t)
            indeg[t] += 1
    queue = [i for i in ids if indeg[i] == 0]
    queue.sort(key=lambda i: 0 if kind.get(i) == "input" else 1)
    out: List[str] = []
    while queue:
        cur = queue.pop(0)
        out.append(cur)
        for nxt in succ[cur]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                queue.append(nxt)
    for i in ids:
        if i not in out:
            out.append(i)
    return out


# --------------------------------------------------------------------------- #
# 单个节点的原生代码块
# --------------------------------------------------------------------------- #
def _block_header(node: Dict[str, Any]) -> str:
    label = node.get("label") or node["kind"]
    return (
        f"{BLOCK_BEGIN}\n"
        f"# 节点：{label}  ({node['name']})  类型：{node['kind']}\n"
        f"{BLOCK_END}\n"
    )


def _block_input(node: Dict[str, Any]) -> str:
    fn = _pyid(node["name"])
    return (
        f"def {fn}(state: AgentState) -> dict:\n"
        f'    """{node.get("label") or "输入"} —— 智能体的入口，接收用户输入。"""\n'
        f'    return {{"data": state.get("data", "")}}\n'
    )


def _block_output(node: Dict[str, Any]) -> str:
    fn = _pyid(node["name"])
    source = _text(_params(node), "source", "auto") or "auto"
    return (
        f"def {fn}(state: AgentState) -> dict:\n"
        f'    """{node.get("label") or "输出"} —— 智能体的出口，把结果交给调用方。"""\n'
        f"    source = {_q(source)}\n"
        f'    if source == "data":\n'
        f'        return {{"data": state.get("data", "")}}\n'
        f'    if source in ("answer", "agent", "auto"):\n'
        f'        answer = state.get("answer")\n'
        f'        if answer not in (None, ""):\n'
        f'            return {{"data": answer}}\n'
        f'        if source == "answer":\n'
        f'            return {{"data": ""}}\n'
        f'    for item in reversed(list(state.get("trace") or [])):\n'
        f'        if item.get("node") == source or item.get("kind") == source:\n'
        f'            return {{"data": item.get("output", "")}}\n'
        f'    return {{"data": state.get("data", "")}}\n'
    )


def _block_tool(node: Dict[str, Any]) -> str:
    fn = _pyid(node["name"])
    kind = _kind_of(node)
    p = _params(node)
    desc = node.get("description") or node.get("label") or "工具"

    # 内置工具预设：直接生成对应实现，不再是空占位
    preset = _text(p, "preset", "")
    spec = TOOL_PRESETS.get(preset) if preset else None
    if spec:
        body = spec["native"]
        for placeholder, key in (("__URL__", "url"), ("__BODY__", "body"), ("__PATH__", "path")):
            body = body.replace(placeholder, _text(p, key, ""))
        arg = spec.get("args") or "query: str"
        return (
            f"@tool\n"
            f"def {fn}({arg}) -> str:\n"
            f'    """{desc}"""\n'
            f"{body}"
        )

    if kind == "web_search":
        body = (
            '    from langchain_community.tools import DuckDuckGoSearchRun\n'
            '    return DuckDuckGoSearchRun().run(query)\n'
        )
        arg = "query: str"
    elif kind == "http_request":
        url = _text(p, "url", "")
        body = (
            '    import urllib.request\n'
            f"    url = {_q(url)} or query\n"
            '    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})\n'
            '    with urllib.request.urlopen(req, timeout=20) as resp:\n'
            '        return resp.read().decode("utf-8", "replace")[:4000]\n'
        )
        arg = "query: str"
    elif kind == "sql_query":
        default_sql = _text(p, "sql", "")
        return (
            f"@tool\n"
            f"def {fn}(sql: str = {_q(default_sql)}) -> str:\n"
            f'    """{desc}"""\n'
            f"    from runtime_sdk import project_query_data\n"
            f'    rows = project_query_data(sql, limit=100)\n'
            f"    return str(rows)[:4000]\n"
        )
    else:
        body = f'    return f"[{fn}] 尚未实现：{{query}}"\n'
        arg = "query: str"
    return (
        f"@tool\n"
        f"def {fn}({arg}) -> str:\n"
        f'    """{desc}"""\n'
        f"{body}"
    )


def _block_llm(node: Dict[str, Any]) -> str:
    fn = _pyid(node["name"])
    kind = _kind_of(node)
    p = _params(node)
    system = _text(p, "system_prompt") or _text(p, "system")
    if not system:
        defaults = {
            "planner": "你是一个任务规划专家。把目标拆成有序、可执行的步骤，每行一步；"
                       "输入只是寒暄、闲聊或没有可拆解目标时，原样返回输入，不要追问。",
            "observation": "把工具返回的结果压缩成 3 条以内的关键观察；没有工具结果时保留原始回答的要点。",
            "review_observation": "判断现有观察是否已经够用：够用就一句话确认；"
                                  "只有确实缺关键信息时才列出缺口，不要展开长分析。",
            "formatter": "你是格式化工具：把输入原样输出，最多调整 Markdown 结构；"
                         "不得增删内容、不得添加解释或判断。",
            "format_observations": "把多轮观察归并成结构化上下文：只做合并与去重，不新增事实、不编造标题。",
            "summarize": "把内容压缩成要点，保留关键数字与结论。",
            "translate": "按要求翻译内容，保持原意与语气。",
            "classify": "判断输入属于哪一类，只输出类别名。",
            "rewrite": "按目标风格重写内容，保持信息不变。",
        }
        system = defaults.get(kind, node.get("description") or "你是一个严谨的助手。")
    temperature = _num(p, "temperature", 0.3)
    prompt_var = f"{fn.upper()}_PROMPT"
    return (
        f"{prompt_var} = ChatPromptTemplate.from_messages([\n"
        f"    (\"system\", {_q(system)}),\n"
        f"    (\"human\", \"{{input}}\"),\n"
        f"])\n"
        f"\n"
        f"def {fn}(state: AgentState) -> dict:\n"
        f'    """{node.get("label") or kind}"""\n'
        f"    model = {_llm_var(node)}.bind(temperature={temperature})\n"
        f"    text = _stream(model, {prompt_var}.format_messages(input=state.get(\"data\", \"\")),\n"
        f"                   {_q(node['id'])}, {_q(node['name'])})\n"
        f'    return {{"data": text}}\n'
    )


def _agent_tool_ids(spec: Dict[str, Any], node_id: str) -> List[str]:
    """这个 agent 实际能用的工具：从它出发 BFS，遇到 tool 收下，遇到别的 agent 停。

    必须和预览执行器 runner.GraphRunner.tools_for 完全一致——同一张画布在
    「预览」和「原生」两种模式下，每个 agent 可见的工具列表不能有两套答案。
    """
    by_source: Dict[str, List[str]] = {}
    for e in spec.get("edges", []):
        by_source.setdefault(e["source"], []).append(e["target"])
    kinds = {n["id"]: _kind_of(n) for n in spec.get("nodes", [])}
    found: List[str] = []
    seen = {node_id}
    queue = [node_id]
    while queue:
        cur = queue.pop(0)
        for tid in by_source.get(cur, []):
            if tid in seen:
                continue
            seen.add(tid)
            kind = kinds.get(tid)
            if kind in TOOL_KINDS:
                found.append(tid)
                queue.append(tid)
            elif kind in AGENT_KINDS:
                continue  # 不跨 agent 借用工具
    return found


def _block_agent(node: Dict[str, Any], spec: Dict[str, Any] | None = None) -> str:
    fn = _pyid(node["name"])
    p = _params(node)
    mode = _text(p, "mode", "react")
    max_steps = int(_num(p, "max_steps", 6))
    system = _text(p, "system_prompt") or (
        "你是一个能调用工具的智能体。回答前先想清楚需要哪些信息，"
        "必要时调用工具，最后给出最终答案。"
    )
    # 每个 agent 只拿自己下游的工具；没有 spec（单独生成节点块）时退回全量
    tools_var = f"TOOLS_{fn}" if spec else "TOOLS"
    return (
        f"def {fn}(state: AgentState) -> dict:\n"
        f'    """{node.get("label") or "Agent"} —— 推理模式：{mode}，最多 {max_steps} 步。"""\n'
        f'    task = state.get("data", "")\n'
        f'    origin = state.get("user_input", "")\n'
        f"    if origin and origin != task:\n"
        f'        task = f"{{origin}}\\n\\n## 上一轮观察 / 反馈\\n{{task}}\\n\\n请结合原始问题作答。"\n'
        f"    agent = _get_agent({_q(node['id'])}, lambda: create_agent(\n"
        f"        model={_llm_var(node)},\n"
        f"        tools={tools_var},\n"
        f"        system_prompt={_q(system)},\n"
        f"    ))\n"
        f"    try:\n"
        f"        answer = _agent_stream(agent, task, {_q(node['id'])}, {_q(node['name'])},\n"
        f"                               {max_steps * 2 + 2})\n"
        f"    except Exception:  # noqa: BLE001\n"
        f"        result = agent.invoke(\n"
        f'            {{"messages": [{{"role": "user", "content": task}}]}},\n'
        f"            config={{\"recursion_limit\": {max_steps * 2 + 2}}},\n"
        f"        )\n"
        f"        messages = result.get(\"messages\") or []\n"
        f"        answer = str(getattr(messages[-1], \"content\", \"\")) if messages else \"\"\n"
        f'    return {{"data": answer, "answer": answer}}\n'
    )


def _block_router(node: Dict[str, Any]) -> str:
    fn = _pyid(node["name"])
    p = _params(node)
    question = (
        _text(p, "expression") or _text(p, "condition") or _text(p, "rule")
        or _text(p, "question") or "该请求是否需要调用工具？"
    )
    # 循环上限：默认给 4 次，避免画布上没填这个参数时第一轮就被"强制收敛"
    max_loops = int(_num(p, "max_loops", 4))
    # 超限后走哪条边：默认 false（多数画布用它做出口），可在节点参数里改成 true
    exit_handle = "true" if str(_text(p, "exit_handle", "false")).lower() == "true" else "false"
    llm_var = _llm_var(node)
    name = _q(node["name"])
    nid = _q(node["id"])
    return (
        f"def {fn}(state: AgentState) -> dict:\n"
        f'    """{node.get("label") or "分支"} —— 按判别问题决定走 true 还是 false。"""\n'
        f'    text = str(state.get("data", ""))\n'
        f"    question = {_q(question)}\n"
        f"    verdict = {llm_var}.bind(temperature=0).invoke([\n"
        f'        {{"role": "system", "content": "你只输出 true 或 false，不要解释。"}},\n'
        f'        {{"role": "user", "content": f"判别问题：{{question}}\\n\\n待判内容：\\n{{text}}\\n\\n只回答 true 或 false。"}},\n'
        f"    ]).content.strip().lower()\n"
        f'    branch = "true" if verdict.startswith("true") else "false"\n'
        f'    rounds = int(state.get("loop_count") or 0) + 1\n'
        f"    max_loops = {max_loops}\n"
        f'    if rounds > max_loops and branch != {_q(exit_handle)}:\n'
        f'        branch = {_q(exit_handle)}\n'
        f'        _emit({{"event": "log", "level": "warn", "node": {nid}, "name": {name},\n'
        f'               "message": f"已到循环上限 {{max_loops}} 次，强制走出口"}})\n'
        f'    _emit({{"event": "route", "node": {nid}, "name": {name},\n'
        f'           "branch": branch, "reason": _brief(verdict, 120)}})\n'
        f'    return {{"data": text, "route": branch, "loop_count": rounds}}\n'
    )


def _block_critic(node: Dict[str, Any]) -> str:
    """评审：让模型按给定标准挑毛病，并给出通过与否。"""
    fn = _pyid(node["name"])
    p = _params(node)
    standard = _q(_text(p, "standard", "准确性、完整性、可用性"))
    llm_var = _llm_var(node)
    return (
        f"def {fn}(state: AgentState) -> dict:\n"
        f'    """{node.get("label") or "评审"} —— 按标准挑问题并判定是否通过。"""\n'
        f'    text = str(state.get("data", ""))\n'
        f"    standard = {standard}\n"
        f"    review = {llm_var}.invoke([\n"
        f'        {{"role": "system", "content": "你是严格的评审者。先列问题，再判定是否通过。"}},\n'
        f'        {{"role": "user", "content": f"评审标准：{{standard}}\\n\\n待审内容：\\n{{text}}"}},\n'
        f"    ]).content.strip()\n"
        f'    passed = "不通过" not in review\n'
        f'    _emit({{"event": "log", "node": {_q(node["id"])}, "name": {_q(node["name"])},\n'
        f'           "message": "评审结论：" + ("通过" if passed else "不通过")}})\n'
        f'    return {{"data": text, "review": review, "passed": passed}}\n'
    )


def _block_self_check(node: Dict[str, Any]) -> str:
    """自检：确认输出是否满足约束，不满足就把问题带出去。"""
    fn = _pyid(node["name"])
    p = _params(node)
    checks = _q(_text(p, "checks", "是否回答了原问题、是否有自相矛盾、是否包含未经验证的断言"))
    llm_var = _llm_var(node)
    return (
        f"def {fn}(state: AgentState) -> dict:\n"
        f'    """{node.get("label") or "自检"} —— 逐条核对输出，返回问题清单。"""\n'
        f'    text = str(state.get("data", ""))\n'
        f"    checks = {checks}\n"
        f"    verdict = {llm_var}.invoke([\n"
        f'        {{"role": "system", "content": "你是质检员，只输出发现的问题，没问题就输出 OK。"}},\n'
        f'        {{"role": "user", "content": f"检查项：{{checks}}\\n\\n内容：\\n{{text}}"}},\n'
        f"    ]).content.strip()\n"
        f'    ok = verdict.upper().startswith("OK")\n'
        f'    return {{"data": text, "check_result": verdict, "ok": ok}}\n'
    )


def _block_merge(node: Dict[str, Any]) -> str:
    """合并：把上游几路结果拼成一份（保序、去重、按分隔符）。"""
    fn = _pyid(node["name"])
    p = _params(node)
    sep = _text(p, "separator", "\n\n")
    return (
        f"def {fn}(state: AgentState) -> dict:\n"
        f'    """{node.get("label") or "汇总"} —— 把多路结果合并成一份。"""\n'
        f"    items = state.get(\"results\")\n"
        f'    if not items:\n'
        f'        items = [state.get("data", "")]\n'
        f'    if isinstance(items, str):\n'
        f"        items = [items]\n"
        f'    parts, seen = [], set()\n'
        f"    for it in items:\n"
        f'        s = it if isinstance(it, str) else json.dumps(it, ensure_ascii=False)\n'
        f"        s = (s or \"\").strip()\n"
        f"        if s and s not in seen:\n"
        f"            seen.add(s)\n"
        f"            parts.append(s)\n"
        f'    merged = {_q(sep)}.join(parts)\n'
        f'    return {{"data": merged, "merged_count": len(parts)}}\n'
    )


def _block_system_prompt(node: Dict[str, Any]) -> str:
    """系统提示词：按人设生成一段稳定的 system prompt，供后续节点复用。"""
    fn = _pyid(node["name"])
    p = _params(node)
    persona = _q(_text(p, "persona", "你是一名严谨、务实的助手。"))
    llm_var = _llm_var(node)
    return (
        f"def {fn}(state: AgentState) -> dict:\n"
        f'    """{node.get("label") or "系统提示词"} —— 生成并放进 state，供下游复用。"""\n'
        f"    base = {persona}\n"
        f'    task = str(state.get("data", ""))\n'
        f"    prompt = {llm_var}.invoke([\n"
        f'        {{"role": "system", "content": "擅长写提示词，输出一段可直接使用的 system prompt。"}},\n'
        f'        {{"role": "user", "content": f"人设：{{base}}\\n本次任务：{{task}}\\n请据此写出 system prompt。"}},\n'
        f"    ]).content.strip()\n"
        f'    return {{"data": task, "system_prompt": prompt}}\n'
    )


def _block_intent(node: Dict[str, Any]) -> str:
    """意图识别：让模型从预定义意图里选一个，并给出置信度。"""
    fn = _pyid(node["name"])
    p = _params(node)
    intents = p.get("intents") or ["咨询", "任务执行", "闲聊", "投诉", "其他"]
    if not isinstance(intents, list):
        intents = ["咨询", "任务执行", "闲聊", "投诉", "其他"]
    llm_var = _llm_var(node)
    return (
        f"def {fn}(state: AgentState) -> dict:\n"
        f'    """{node.get("label") or "意图识别"} —— 归到预定义意图之一。"""\n'
        f'    text = str(state.get("data", ""))\n'
        f"    intents = {json.dumps(intents, ensure_ascii=False)}\n"
        f"    raw = {llm_var}.bind(temperature=0).invoke([\n"
        f'        {{"role": "system", "content": "只输出 JSON，不要多余文字。"}},\n'
        f'        {{"role": "user", "content": f"可选意图：{{intents}}\\n\\n用户输入：{{text}}\\n\\n"\n'
        f'                                       "只输出 JSON：intent 填其中一个，confidence 填 0 到 1 的数"}},\n'
        f"    ]).content\n"
        f"    info = _parse_json(raw, {{}})\n"
        f'    intent = str(info.get("intent") or "").strip()\n'
        f"    if intent not in intents:\n"
        f"        intent = next((i for i in intents if i in text), intents[-1])\n"
        f"    try:\n"
        f'        conf = float(info.get("confidence") or 0)\n'
        f"    except (TypeError, ValueError):\n"
        f"        conf = 0.0\n"
        f'    return {{"data": text, "intent": intent, "confidence": conf}}\n'
    )


def _block_doc_loader(node: Dict[str, Any]) -> str:
    fn = _pyid(node["name"])
    p = _params(node)
    default_path = _q(_text(p, "path", ""))
    return (
        f"def {fn}(state: AgentState) -> dict:\n"
        f'    """{node.get("label") or "文档加载"} —— 把文本类文档读成纯文本。"""\n'
        f"    from pathlib import Path as _Path\n"
        f"    raw_path = {default_path} or str(state.get(\"data\", \"\")).strip()\n"
        f"    if not raw_path:\n"
        f'        raise ValueError("doc_loader 需要文件路径（参数 path 或输入内容）")\n'
        f"    path = _Path(raw_path)\n"
        f"    if not path.is_absolute():\n"
        f"        path = _Path(__file__).resolve().parent / path\n"
        f"    # 输入不是可读文件时，把它当成已经加载好的正文，链路照样能往下走\n"
        f"    if not path.exists():\n"
        f'        _emit({{"event": "log", "level": "warn", "node": {_q(node["id"])},\n'
        f'               "name": {_q(node["name"])}, "message": "输入不是文件，按正文处理"}})\n'
        f'        return {{"data": raw_path, "source": "inline"}}\n'
        f"    suffix = path.suffix.lower()\n"
        f'    if suffix == ".pdf":\n'
        f'        try:\n'
        f"            from pypdf import PdfReader\n"
        f"        except ImportError as exc:\n"
        f'            raise RuntimeError("读 PDF 需要 pypdf：pip install pypdf") from exc\n'
        f'        text = "\\n".join((pg.extract_text() or "") for pg in PdfReader(str(path)).pages)\n'
        f'    elif suffix == ".docx":\n'
        f"        try:\n"
        f"            import docx\n"
        f"        except ImportError as exc:\n"
        f'            raise RuntimeError("读 docx 需要 python-docx：pip install python-docx") from exc\n'
        f'        text = "\\n".join(p_.text for p_ in docx.Document(str(path)).paragraphs)\n'
        f"    else:\n"
        f'        text = path.read_text(encoding="utf-8", errors="replace")\n'
        f'    _emit({{"event": "log", "node": {_q(node["id"])}, "name": {_q(node["name"])},\n'
        f'           "message": f"已读取 {{path.name}}，{{len(text)}} 字符"}})\n'
        f'    return {{"data": text, "source": str(path.name)}}\n'
    )


def _block_splitter(node: Dict[str, Any]) -> str:
    fn = _pyid(node["name"])
    p = _params(node)
    size = int(_num(p, "chunk_size", 600))
    overlap = int(_num(p, "overlap", 80))
    return (
        f"def {fn}(state: AgentState) -> dict:\n"
        f'    """{node.get("label") or "文本切分"} —— 按段落切块，带重叠。"""\n'
        f'    text = str(state.get("data", ""))\n'
        f"    size, overlap_chars = {size}, {overlap}\n"
        f"    step = max(1, size - overlap_chars)\n"
        f"    chunks = [text[i:i + size] for i in range(0, len(text), step)] if text else []\n"
        f"    chunks = [c.strip() for c in chunks if c.strip()]\n"
        f'    _emit({{"event": "log", "node": {_q(node["id"])}, "name": {_q(node["name"])},\n'
        f'           "message": f"切成 {{len(chunks)}} 块"}})\n'
        f'    return {{"data": chunks, "chunk_count": len(chunks)}}\n'
    )


def _block_indexer(node: Dict[str, Any]) -> str:
    """向量类节点：复用项目自带的 providers 适配层。

    配置读 config.json，所以同一段代码在 SQLite / Chroma / Qdrant / pgvector /
    Milvus 之间切换不用改；导出的项目脱离平台也照样能跑。
    """
    fn = _pyid(node["name"])
    kind = _kind_of(node)
    p = _params(node)
    collection = _text(p, "collection", "")
    nid = _q(node["id"])
    nname = _q(node["name"])
    use_coll = f"    project_use_collection({_q(collection)})\n" if collection else ""

    if kind == "embedding":
        return (
            f"def {fn}(state: AgentState) -> dict:\n"
            f'    """{node.get("label") or "向量化"} —— 走 config.json 里配置的向量模型。"""\n'
            f"    from runtime_sdk import project_embed\n"
            f'    text = str(state.get("data", ""))\n'
            f"    vec = project_embed(text)\n"
            f'    _emit({{"event": "embedding", "node": {nid}, "name": {nname},\n'
            f'           "dim": len(vec)}})\n'
            f'    return {{"data": vec, "text": text, "dim": len(vec)}}\n'
        )

    if kind == "vector_store":
        action = str(_text(p, "action", "search")).lower()
        top_k = int(_num(p, "top_k", 4))
        raw_where = p.get("where")
        where_literal = "None"
        if isinstance(raw_where, str) and raw_where.strip():
            try:
                where_literal = json.dumps(json.loads(raw_where), ensure_ascii=False)
            except Exception:  # noqa: BLE001
                where_literal = "None"
        elif isinstance(raw_where, dict):
            where_literal = json.dumps(raw_where, ensure_ascii=False)

        if action == "upsert":
            return (
                f"def {fn}(state: AgentState) -> dict:\n"
                f'    """{node.get("label") or "向量库"} —— 写入 config.json 里配置的向量库。"""\n'
                f"    from runtime_sdk import project_vector_upsert\n"
                f"    from runtime_sdk import project_use_collection\n"
                f"{use_coll}"
                f'    text = str(state.get("data", ""))\n'
                f'    result = project_vector_upsert(text, {{"node": {nname}}})\n'
                f'    _emit({{"event": "log", "node": {nid}, "name": {nname},\n'
                f'           "message": f"已写入 {{result.get(\'backend\')}}"}})\n'
                f'    return {{"data": result, "id": result.get("id")}}\n'
            )
        return (
            f"def {fn}(state: AgentState) -> dict:\n"
            f'    """{node.get("label") or "向量库"} —— 从 config.json 里配置的向量库检索。"""\n'
            f"    from runtime_sdk import project_vector_search\n"
            f"    from runtime_sdk import project_use_collection\n"
            f"{use_coll}"
            f'    query = str(state.get("data", ""))\n'
            f"    hits = project_vector_search(query, top_k={top_k}, where={where_literal})\n"
            f'    _emit({{"event": "retrieval", "node": {nid}, "name": {nname},\n'
            f'           "count": len(hits)}})\n'
            f'    return {{"data": hits, "query": query, "hit": len(hits)}}\n'
        )

    # vector_indexer：批量入库
    return (
        f"def {fn}(state: AgentState) -> dict:\n"
        f'    """{node.get("label") or "向量入库"} —— 写进 config.json 里配置的向量库。"""\n'
        f"    from runtime_sdk import project_vector_upsert\n"
        f"    from runtime_sdk import project_use_collection\n"
        f"{use_coll}"
        f'    data = state.get("data")\n'
        f"    # 上游直接给向量说明接线错了：入库要接在文本后面\n"
        f"    if isinstance(data, list) and data and all(isinstance(x, (int, float)) for x in data):\n"
        f'        _emit({{"event": "log", "level": "warn", "node": {nid}, "name": {nname},\n'
        f'               "message": "上游是向量而不是文本：vector_indexer 应接在文本节点后面"}})\n'
        f'        return {{"data": data, "indexed": 0, "skipped": "vector_input"}}\n'
        f"    if isinstance(data, list) and data and all(isinstance(x, str) for x in data):\n"
        f"        chunks = data\n"
        f"    else:\n"
        f'        chunks = [str(data or "")]\n'
        f'    chunks = [c for c in chunks if str(c).strip()]\n'
        f"    for chunk in chunks:\n"
        f'        project_vector_upsert(str(chunk), {{"node": {nname}}})\n'
        f'    _emit({{"event": "log", "node": {nid}, "name": {nname},\n'
        f'           "message": f"入库 {{len(chunks)}} 块"}})\n'
        f'    return {{"data": str(data or ""), "text": str(data or ""),\n'
        f'             "indexed": len(chunks)}}\n'
    )


def _block_hybrid(node: Dict[str, Any]) -> str:
    """混合检索：向量库 + 文件关键词各取一份。"""
    fn = _pyid(node["name"])
    p = _params(node)
    top_k = int(_num(p, "top_k", 4))
    nid = _q(node["id"])
    nname = _q(node["name"])
    raw_where = p.get("where")
    where_literal = "None"
    if isinstance(raw_where, str) and raw_where.strip():
        try:
            where_literal = json.dumps(json.loads(raw_where), ensure_ascii=False)
        except Exception:  # noqa: BLE001
            where_literal = "None"
    elif isinstance(raw_where, dict):
        where_literal = json.dumps(raw_where, ensure_ascii=False)
    return (
        f"def {fn}(state: AgentState) -> dict:\n"
        f'    """{node.get("label") or "混合检索"} —— 向量库召回 + 文件关键词召回。"""\n'
        f"    from runtime_sdk import project_retrieve, project_vector_search\n"
        f'    query = str(state.get("data", ""))\n'
        f"    hits = project_vector_search(query, top_k={top_k}, where={where_literal})\n"
        f'    keywords = project_retrieve(query, top_k={top_k}, mode="keyword")\n'
        f'    _emit({{"event": "retrieval", "node": {nid}, "name": {nname},\n'
        f'           "vector": len(hits), "keyword": len(keywords)}})\n'
        f'    return {{"data": hits or keywords, "query": query,\n'
        f'             "vector": hits, "keyword": keywords}}\n'
    )


def _block_retriever(node: Dict[str, Any]) -> str:
    fn = _pyid(node["name"])
    p = _params(node)
    top_k = int(_num(p, "top_k", 4))
    return (
        f"def {fn}(state: AgentState) -> dict:\n"
        f'    """{node.get("label") or "检索"} —— 从项目内的 .store.db 里按相关度取片段。\n'
        f"\n"
        f"    这里给的是可运行的关键词 + 字符重合方案；想换成真正的向量库，\n"
        f"    把 _score 换成 embedding 余弦即可，接口不用改。\n"
        f'    """\n'
        f"    import sqlite3\n"
        f"    from pathlib import Path as _Path\n"
        f"\n"
        f'    query = str(state.get("data", ""))\n'
        f"    top_k = {top_k}\n"
        f'    db = _Path(__file__).resolve().parent / ".store.db"\n'
        f"    if not db.exists():\n"
        f'        _emit({{"event": "log", "level": "warn", "node": {_q(node["id"])},\n'
        f'               "name": {_q(node["name"])}, "message": "索引库还不存在，先跑一次入库"}})\n'
        f'        return {{"data": query, "docs": []}}\n'
        f"    conn = sqlite3.connect(db)\n"
        f"    rows = conn.execute(\"SELECT text FROM chunks\").fetchall()\n"
        f"    conn.close()\n"
        f"    q_tokens = set(query.lower().split())\n"
        f"\n"
        f"    def _score(text: str) -> float:\n"
        f"        low = text.lower()\n"
        f"        hit = sum(1 for w in q_tokens if w and w in low)\n"
        f"        return hit / (len(q_tokens) or 1) + (0.5 if query and query in low else 0)\n"
        f"\n"
        f"    ranked = sorted(((t, _score(t)) for (t,) in rows), key=lambda x: x[1], reverse=True)\n"
        f"    picked = [t for t, s in ranked[:top_k] if s > 0]\n"
        f'    context = "\\n\\n".join(picked)\n'
        f'    _emit({{"event": "retrieval", "node": {_q(node["id"])}, "name": {_q(node["name"])},\n'
        f'           "count": len(picked)}})\n'
        f'    return {{"data": context or query, "docs": picked, "hit": len(picked)}}\n'
    )


def _block_dataset(node: Dict[str, Any]) -> str:
    """数据集读取节点：按逻辑名从外部数据中台取数（连接配置在 integrations.json）。"""
    fn = _pyid(node["name"])
    p = _params(node)
    dataset = _text(p, "dataset", "")
    filters = p.get("filters") or {}
    if isinstance(filters, str):
        try:
            filters = json.loads(filters) if filters.strip() else {}
        except Exception:  # noqa: BLE001
            filters = {}
    limit = int(_num(p, "limit", 100))
    return (
        f"def {fn}(state: AgentState) -> dict:\n"
        f'    """{node.get("label") or "数据集读取"} —— 从外部数据中台按逻辑名取数。"""\n'
        f"    from integrations.data_client import read_dataset\n"
        f"    rows = read_dataset({_q(dataset)}, filters={json.dumps(filters, ensure_ascii=False)},\n"
        f"                        limit={limit})\n"
        f'    return {{"data": rows, "dataset": {_q(dataset)}}}\n'
    )


def _block_memory(node: Dict[str, Any]) -> str:
    fn = _pyid(node["name"])
    limit = int(_num(_params(node), "window", 10))
    return (
        f"def {fn}(state: AgentState) -> dict:\n"
        f'    """{node.get("label") or "记忆"} —— 保留最近 {limit} 轮对话。"""\n'
        f'    history = list(state.get("history") or [])\n'
        f'    history.append(str(state.get("data", "")))\n'
        f'    return {{"data": state.get("data", ""), "history": history[-{limit}:]}}\n'
    )


def _block_wiki(node: Dict[str, Any]) -> str:
    """LLM Wiki 节点：入库时让模型读懂并写成可读页面，查询时直接读页。

    这两块用纯 Python + llm 实现，不 import runtime_sdk，
    保证 agent.py 拿出去仍然是自包含的。
    """
    fn = _pyid(node["name"])
    p = _params(node)
    if _kind_of(node) == "wiki_ingest":
        title_expr = _q(_text(p, "title"))
        source_expr = _q(_text(p, "source"))
        return (
            f"def {fn}(state: AgentState) -> dict:\n"
            f'    """Wiki 入库：让模型提炼标题 / 摘要 / 要点，写成一页 markdown。"""\n'
            f"    import json as _json\n"
            f"    from pathlib import Path as _Path\n"
            f"\n"
            f'    wiki = _Path(__file__).resolve().parent / "wiki"\n'
            f"    wiki.mkdir(exist_ok=True)\n"
            f'    text = str(state.get("data", "") or "")\n'
            f"    info = {{}}\n"
            f"    try:\n"
            f"        raw = llm.invoke(\n"
            f'            "把下面这段资料整理成一页 wiki，只输出 JSON："\n'
            f"            '{{\"title\": \"\", \"summary\": \"\", \"points\": []}}'\n"
            f'            "\\n\\n" + text[:4000]\n'
            f"        ).content\n"
            f'        s, e = raw.find("{{"), raw.rfind("}}")\n'
            f"        if s >= 0 and e > s:\n"
            f"            info = _json.loads(raw[s:e + 1])\n"
            f"    except Exception:\n"
            f"        info = {{}}\n"
            f'    title = {title_expr} or str(info.get("title") or "").strip() or text[:24]\n'
            f'    slug = "".join(c if (c.isalnum() or c in "-_") else "-" for c in title.lower())[:48] or "page"\n'
            f'    summary = str(info.get("summary") or "").strip()\n'
            f'    points = info.get("points") or []\n'
            f'    lines = ["# " + title, "", "## 摘要", "", summary, "", "## 要点", ""]\n'
            f'    lines += ["- " + str(x) for x in points]\n'
            f'    lines += ["", "## 原文", "", text[:8000], ""]\n'
            f'    (wiki / (slug + ".md")).write_text("\\n".join(lines), encoding="utf-8")\n'
            f'    return {{"data": _json.dumps({{"slug": slug, "title": title, "source": {source_expr}}},\n'
            f'                              ensure_ascii=False)}}\n'
        )

    top_k = int(_num(p, "top_k", 3))
    return (
        f"def {fn}(state: AgentState) -> dict:\n"
        f'    """Wiki 检索：列出现有页面，按字面重合粗排后取前几页。"""\n'
        f"    from pathlib import Path as _Path\n"
        f"\n"
        f'    wiki = _Path(__file__).resolve().parent / "wiki"\n'
        f'    query = str(state.get("data", "") or "")\n'
        f"    pages = []\n"
        f"    if wiki.exists():\n"
        f'        for f in sorted(wiki.glob("*.md")):\n'
        f'            pages.append({{"slug": f.stem,\n'
        f'                           "text": f.read_text(encoding="utf-8", errors="replace")[:4000]}})\n'
        f"    if not pages:\n"
        f'        return {{"data": ""}}\n'
        f"    words = [w for w in query.lower().split() if w]\n"
        f"    pages.sort(key=lambda pg: sum(1 for w in words if w in pg[\"text\"].lower()),\n"
        f"               reverse=True)\n"
        f"    top = pages[:{top_k}]\n"
        f'    context = "\\n\\n".join("## " + pg["slug"] + "\\n" + pg["text"] for pg in top)\n'
        f'    return {{"data": context}}\n'
    )


def _block_generic(node: Dict[str, Any]) -> str:
    fn = _pyid(node["name"])
    desc = node.get("description") or node.get("label") or node["kind"]
    return (
        f"def {fn}(state: AgentState) -> dict:\n"
        f'    """{desc}"""\n'
        f"    # 这个节点类型还没有专门的原生写法，先用一次模型调用占位\n"
        f'    msg = {_llm_var(node)}.invoke(f"{desc}\\n\\n输入：{{state.get(\'data\', \'\')}}")\n'
        f'    return {{"data": msg.content}}\n'
    )


def node_block(node: Dict[str, Any], spec: Dict[str, Any] | None = None) -> str:
    """生成单个节点在 agent.py 里的代码块。"""
    kind = _kind_of(node)
    header = _block_header(node)
    decl = _llm_decl(node)

    if kind == "input":
        body = _block_input(node)
    elif kind == "output":
        body = _block_output(node)
    elif kind in ("wiki_ingest", "wiki_query"):
        body = _block_wiki(node)
    elif kind == "critic":
        body = _block_critic(node)
    elif kind == "self_check":
        body = _block_self_check(node)
    elif kind in ("merge", "join", "merger"):
        body = _block_merge(node)
    elif kind == "system_prompt":
        body = _block_system_prompt(node)
    elif kind == "intent_recognizer":
        body = _block_intent(node)
    elif kind == "doc_loader":
        body = _block_doc_loader(node)
    elif kind in ("text_splitter", "chunker"):
        body = _block_splitter(node)
    elif kind in ("vector_indexer", "embedding", "vector_store"):
        body = _block_indexer(node)
    elif kind == "hybrid_retriever":
        body = _block_hybrid(node)
    elif kind in TOOL_KINDS:
        body = _block_tool(node)
    elif kind in ROUTE_KINDS:
        body = _block_router(node)
    elif kind in ("retriever", "vector_retriever", "rag", "rag_retriever",
                  "hybrid_retriever", "bm25_search"):
        body = _block_retriever(node)
    elif kind in ("dataset_reader", "dataset"):
        body = _block_dataset(node)
    elif kind in ("memory", "conversation_memory"):
        body = _block_memory(node)
    elif kind == "agent" or kind in ("supervisor", "worker", "autogen_assistant",
                                     "crewai_agent", "group_chat", "debate"):
        body = _block_agent(node, spec)
    elif kind in LLM_KINDS:
        body = _block_llm(node)
    else:
        body = _block_generic(node)

    parts = [header, "\n"]
    if decl:
        parts.append(decl + "\n")
    parts.append(body + "\n")
    return "".join(parts)


# --------------------------------------------------------------------------- #
# agent.py 整体
# --------------------------------------------------------------------------- #
_HEADER_LANGCHAIN = '''"""{name} · {framework_label}

由 MineAgent 根据画布生成，可以直接改、也可以直接拿去部署。

代码是主体，画布上的每个节点都对应下面一个带 ═══ 标记的代码块；
在网页里编辑节点代码，改的就是这里的同一段。

用法：
    python agent.py --input "你的问题"
"""
from __future__ import annotations

import contextvars
import functools
import hashlib
import json
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Annotated, Any, TypedDict

from langchain.agents import create_agent
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.prompts import ChatPromptTemplate, PromptTemplate
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph

HERE = Path(__file__).resolve().parent
CFG = json.loads((HERE / "config.json").read_text(encoding="utf-8"))


# ── token 用量：按运行上下文累计，一次 run 结束由 take_usage() 取走 ──
# 用 ContextVar 而不是线程局部变量：节点是在线程池里执行的，只有复制上下文
# （_run_with_timeout 里做了）才能把用量带回来。
_USAGE = contextvars.ContextVar("mineagent_usage", default=None)


def reset_usage() -> None:
    _USAGE.set({"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "calls": 0})


def _usage_add(usage) -> None:
    """累计一次模型调用的 token（同时兼容 OpenAI 和 LangChain 的字段名）。"""
    if not isinstance(usage, dict):
        return
    bucket = _USAGE.get()
    if bucket is None:
        reset_usage()
        bucket = _USAGE.get()
    for dst, keys in (("prompt_tokens", ("input_tokens", "prompt_tokens")),
                      ("completion_tokens", ("output_tokens", "completion_tokens")),
                      ("total_tokens", ("total_tokens",))):
        for key in keys:
            value = usage.get(key)
            if value:
                try:
                    bucket[dst] += int(value)
                except (TypeError, ValueError):
                    pass
                break
    bucket["calls"] += 1


def take_usage() -> dict:
    """取走本次运行的用量统计，并清空。"""
    bucket = dict(_USAGE.get() or {"prompt_tokens": 0, "completion_tokens": 0,
                                   "total_tokens": 0, "calls": 0})
    reset_usage()
    return bucket


class _UsageHandler(BaseCallbackHandler):
    """把所有模型调用的 token 用量记进当前运行上下文。

    挂在模型实例上，invoke / stream / create_agent 内部的调用都能覆盖到，
    比在每个节点里手写记账可靠。
    """

    def on_llm_end(self, response, **kwargs):  # noqa: D401
        llm_output = getattr(response, "llm_output", None) or {}
        _usage_add(llm_output.get("token_usage") or llm_output.get("usage"))


_USAGE_HANDLER = _UsageHandler()


# ── trace id：一次请求一个，日志和节点事件都带上，方便串起整条链路 ──
_TRACE = contextvars.ContextVar("mineagent_trace", default="")


def set_trace_id(value: str) -> None:
    _TRACE.set(str(value or ""))


def get_trace_id() -> str:
    return _TRACE.get() or ""


# ── 工具幂等：同一次运行里、同样参数只真正执行一次，重跑直接回放上次结果 ──
_RUN_ID = uuid.uuid4().hex[:12]
_IDEM_DB = HERE / ".store.db"
_MISS = object()


def _idem_key(node_id: str, arguments: dict) -> str:
    raw = json.dumps({"run": get_trace_id() or _RUN_ID, "node": node_id, "args": arguments},
                     ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _idem_read(key: str):
    try:
        conn = sqlite3.connect(str(_IDEM_DB), timeout=5)
        try:
            conn.execute("CREATE TABLE IF NOT EXISTS tool_calls("
                         "key TEXT PRIMARY KEY, result TEXT, ts REAL)")
            row = conn.execute("SELECT result FROM tool_calls WHERE key=?", (key,)).fetchone()
        finally:
            conn.close()
        return json.loads(row[0]) if row else _MISS
    except Exception:  # noqa: BLE001
        return _MISS


def _idem_write(key: str, value) -> None:
    try:
        conn = sqlite3.connect(str(_IDEM_DB), timeout=5)
        try:
            conn.execute("CREATE TABLE IF NOT EXISTS tool_calls("
                         "key TEXT PRIMARY KEY, result TEXT, ts REAL)")
            conn.execute("INSERT OR REPLACE INTO tool_calls VALUES(?,?,?)",
                         (key, json.dumps(value, ensure_ascii=False, default=str), time.time()))
            conn.commit()
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        pass


def idempotent(node_id: str):
    """给工具加幂等：同一次运行内相同参数不再重复产生副作用。"""

    def decorate(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            key = _idem_key(node_id, {"args": list(args), "kwargs": kwargs})
            hit = _idem_read(key)
            if hit is not _MISS:
                _emit({"event": "log", "level": "info", "node": node_id,
                       "message": "幂等命中，复用上次结果"})
                return hit
            result = fn(*args, **kwargs)
            _idem_write(key, result)
            return result

        return wrapper

    return decorate


# ── 模型：key 从环境变量或 .env 读，不写死在代码里 ──────────────
llm = ChatOpenAI(
    model=os.environ.get("MINEAGENT_MODEL") or CFG.get("model", "deepseek-chat"),
    base_url=os.environ.get("MINEAGENT_BASE_URL") or CFG.get("base_url"),
    api_key=os.environ.get("MINEAGENT_API_KEY") or "EMPTY",
    temperature=CFG.get("temperature", 0.3),
    max_tokens=CFG.get("max_tokens", 2048),
    # 超时必须在 HTTP 层生效：节点级 _track 的超时只是兜底，
    # 真正能中断请求的是这里（默认 120s，可用环境变量覆盖）
    timeout=float(os.environ.get("MINEAGENT_LLM_TIMEOUT") or 120),
    max_retries=int(os.environ.get("MINEAGENT_LLM_MAX_RETRIES") or 2),
    # 流式调用也要带上 token 用量（OpenAI 兼容接口需要显式要 usage）。
    # 个别服务商不认 stream_options，遇到就设 MINEAGENT_STREAM_USAGE=0 关掉。
    stream_usage=str(os.environ.get("MINEAGENT_STREAM_USAGE", "1")).lower() not in ("0", "false", "no"),
    # callbacks 挂在模型上：所有节点（含 create_agent 内部）的调用都会记账
    callbacks=[_USAGE_HANDLER],
)

# ── 运行事件：每个节点执行前后的输入/输出都回传给网页运行面板 ──────
EVENT_PREFIX = "@@EVENT@@"


def _emit(event: dict) -> None:
    try:
        if "trace_id" not in event:
            event = {**event, "trace_id": get_trace_id()}
        print(EVENT_PREFIX + json.dumps(event, ensure_ascii=False, default=str), flush=True)
    except Exception:  # noqa: BLE001
        pass


def _parse_json(text: str, default: Any = None) -> Any:
    """从模型输出里尽力抠出 JSON（允许带 ```json 包裹或前后废话）。"""
    raw = (text or "").strip()
    if not raw:
        return default if default is not None else {}
    fence = raw.find("```")
    if fence >= 0:
        body = raw[fence + 3:]
        if body.lstrip().lower().startswith("json"):
            body = body.lstrip()[4:]
        end = body.find("```")
        raw = body[:end] if end >= 0 else body
        raw = raw.strip()
    try:
        return json.loads(raw)
    except Exception:
        pass
    start = min([i for i in (raw.find("{"), raw.find("[")) if i >= 0] or [-1])
    end = max(raw.rfind("}"), raw.rfind("]"))
    if start >= 0 and end > start:
        try:
            return json.loads(raw[start:end + 1])
        except Exception:
            pass
    return default if default is not None else {}


def _brief(value: Any, limit: int = 1500) -> Any:
    if isinstance(value, str):
        return value[:limit]
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, default=str))
    except Exception:  # noqa: BLE001
        return str(value)[:limit]


def _stream(model, messages, node_id: str = "", name: str = "", interval: float = 0.05) -> str:
    """逐段调模型：边生成边把 token 推给运行面板，最后拼成完整文本。"""
    parts: list = []
    last = 0.0
    usage_seen = None
    try:
        for chunk in model.stream(messages):
            meta = getattr(chunk, "usage_metadata", None)
            if meta:
                usage_seen = meta
            text = getattr(chunk, "content", "")
            if not isinstance(text, str) or not text:
                continue
            parts.append(text)
            now = time.time()
            if now - last >= interval:
                last = now
                _emit({"event": "token", "node": node_id, "name": name, "text": text})
    except Exception:  # noqa: BLE001
        msg = model.invoke(messages)
        return str(getattr(msg, "content", msg))
    if usage_seen:
        # 流式返回的用量：on_llm_end 拿到的 llm_output 可能是空的，这里补一次
        _usage_add(usage_seen)
    return "".join(parts)


def _agent_stream(agent, task: str, node_id: str = "", name: str = "",
                  recursion_limit: int = 14) -> str:
    """跑 agent 并把生成片段推给运行面板，最后从 values 状态里取最终回答。"""
    last_state: dict = {}
    for mode, payload in agent.stream(
        {"messages": [{"role": "user", "content": task}]},
        config={"recursion_limit": recursion_limit},
        stream_mode=["messages", "values"],
    ):
        if mode == "messages":
            chunk, _meta = payload
            text = getattr(chunk, "content", "")
            if isinstance(text, str) and text:
                _emit({"event": "token", "node": node_id, "name": name, "text": text})
        elif mode == "values" and isinstance(payload, dict):
            last_state = payload
    messages = last_state.get("messages") or []
    return str(getattr(messages[-1], "content", "")) if messages else ""


def _run_with_timeout(fn, state, timeout_s: float):
    """给同步节点加超时。

    超时后立刻把控制权交回调用方：cancel + shutdown(wait=False)，
    不再同步等一个仍卡在网络上的调用。真正的硬中断由模型客户端自己的
    timeout（环境变量 MINEAGENT_LLM_TIMEOUT）兜底。
    """
    from concurrent.futures import ThreadPoolExecutor
    from concurrent.futures import TimeoutError as FutureTimeout

    pool = ThreadPoolExecutor(max_workers=1)
    # 复制上下文：节点里累计的 token 用量要能带回调用方
    ctx = contextvars.copy_context()
    future = pool.submit(ctx.run, fn, state)
    try:
        return future.result(timeout=timeout_s)
    except FutureTimeout:
        future.cancel()
        raise TimeoutError(f"节点执行超时（>{timeout_s:g}s）") from None
    finally:
        pool.shutdown(wait=False)


def _retryable(exc: Exception) -> bool:
    """只有网络 / 限流 / 服务端 5xx 这类明确可重放的错误才值得重试。

    超时不重试：那次调用可能还在服务端跑，重试等于重复计费。
    """
    if isinstance(exc, TimeoutError):
        return False
    name = type(exc).__name__.lower()
    if any(k in name for k in ("connection", "ratelimit")):
        return True
    text = str(exc).lower()
    return any(k in text for k in ("429", "503", "connection reset", "connection aborted"))


def _track(fn, node_id: str, name: str = "", label: str = "", kind: str = "llm",
           opts: dict | None = None):
    """包一层：执行超时 / 失败重试 / 错误分流 / 事件回传 / 轨迹记录。"""
    opts = opts or {}
    timeout_s = float(opts.get("timeout_s") or 0)
    max_retries = int(opts.get("max_retries") or 0)
    backoff = float(opts.get("retry_backoff_s") or 0)
    on_error = str(opts.get("on_error") or "block")
    rate = int(opts.get("rate_per_minute") or 0)

    def wrapped(state):
        started = time.time()
        if rate > 0:
            now = time.time()
            window = [t for t in (state.get("__rate__") or []) if now - t < 60]
            if len(window) >= rate:
                wait = 60 - (now - window[0])
                if wait > 0:
                    _emit({"event": "log", "level": "warn", "node": node_id,
                           "name": name or node_id,
                           "message": f"触发限流，等待 {wait:.1f}s"})
                    time.sleep(min(wait, 30))
                window = []
            window.append(time.time())
            state["__rate__"] = window[-rate:]
        _emit({"event": "node_start", "node": node_id, "name": name or node_id,
               "label": label, "kind": kind})
        attempt = 0
        while True:
            try:
                out = _run_with_timeout(fn, state, timeout_s) if timeout_s > 0 else fn(state)
                break
            except Exception as exc:  # noqa: BLE001
                if attempt < max_retries and _retryable(exc):
                    attempt += 1
                    _emit({"event": "log", "level": "warn", "node": node_id,
                           "name": name or node_id,
                           "message": f"第 {attempt} 次重试：{type(exc).__name__}: {exc}"})
                    time.sleep(backoff * attempt)
                    continue
                _emit({"event": "error", "node": node_id, "name": name or node_id,
                       "message": str(exc)})
                if on_error == "edge":
                    # 不中断流程：把错误写进状态，由 conditional edge 送到错误出口
                    out = {"data": f"[节点失败] {exc}", "__error__": str(exc)}
                    break
                raise
        data = out.get("data", "") if isinstance(out, dict) else out
        trace = list(state.get("trace") or [])
        trace.append({"node": name or node_id, "id": node_id, "kind": kind,
                      "output": _brief(data), "attempts": attempt})
        _emit({"event": "node_end", "node": node_id, "name": name or node_id, "kind": kind,
               "duration_ms": int((time.time() - started) * 1000),
               "attempts": attempt, "output": _brief(data)})
        if isinstance(out, dict):
            out["trace"] = trace[-40:]
            # 成功执行后清掉上一轮的错误标记
            if "__error__" not in out:
                out["__error__"] = ""
        return out

    return wrapped


def _merge_value(old: Any, new: Any) -> Any:
    """并行分支同时写同一个键时，用后到的值覆盖，不抛 InvalidUpdateError。"""
    return new if new is not None else old


class AgentState(TypedDict, total=False):
    """整张图共享的状态：data 在节点之间流动，route 承载分支信号。

    并行分支（一个节点连多条出边）会同时回写，所以这些键都挂了合并函数，
    否则 LangGraph 会报 "Can receive only one value per step"。
    """

    data: Annotated[Any, _merge_value]
    route: Annotated[str, _merge_value]
    history: Annotated[list, _merge_value]
    trace: Annotated[list, _merge_value]
    answer: Annotated[Any, _merge_value]
    loop_count: Annotated[int, _merge_value]
    user_input: Annotated[str, _merge_value]


# ── agent 实例缓存：工具集和 system prompt 都是静态的，没必要每次调用重建 ──
_AGENTS: dict = {}


def _get_agent(key: str, build):
    agent = _AGENTS.get(key)
    if agent is None:
        agent = build()
        _AGENTS[key] = agent
    return agent


'''

_HEADER_AUTOGEN = '''"""{name} · {framework_label}

由 MineAgent 根据画布生成，可以直接改、也可以直接拿去部署。
每个画布节点对应下面一个带 ═══ 标记的代码块。

用法：
    python agent.py --input "你的问题"
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated, Any, TypedDict

try:
    from autogen import AssistantAgent, GroupChat, GroupChatManager, UserProxyAgent
except ImportError as _missing:  # pragma: no cover
    raise SystemExit(
        f"缺少 AutoGen 依赖（{_missing}）。先执行：pip install pyautogen ，装好后重新运行本文件即可。"
    ) from _missing
from openai import OpenAI

HERE = Path(__file__).resolve().parent
CFG = json.loads((HERE / "config.json").read_text(encoding="utf-8"))

llm_config = {{
    "config_list": [
        {{
            "model": os.environ.get("MINEAGENT_MODEL") or CFG.get("model", "deepseek-chat"),
            "base_url": os.environ.get("MINEAGENT_BASE_URL") or CFG.get("base_url"),
            "api_key": os.environ.get("MINEAGENT_API_KEY") or "EMPTY",
        }}
    ],
    "temperature": CFG.get("temperature", 0.3),
}}

client = OpenAI(
    base_url=os.environ.get("MINEAGENT_BASE_URL") or CFG.get("base_url"),
    api_key=os.environ.get("MINEAGENT_API_KEY") or "EMPTY",
)


class AgentState(TypedDict, total=False):
    data: Any
    route: str


'''

_HEADER_CREWAI = '''"""{name} · {framework_label}

由 MineAgent 根据画布生成，可以直接改、也可以直接拿去部署。
每个画布节点对应下面一个带 ═══ 标记的代码块。

用法：
    python agent.py --input "你的问题"
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated, Any, TypedDict

try:
    from crewai import Agent, Crew, Process, Task
    from crewai.tools import tool
except ImportError as _missing:  # pragma: no cover
    raise SystemExit(
        f"缺少 CrewAI 依赖（{_missing}）。先执行：pip install crewai ，装好后重新运行本文件即可。"
    ) from _missing
from langchain_openai import ChatOpenAI

HERE = Path(__file__).resolve().parent
CFG = json.loads((HERE / "config.json").read_text(encoding="utf-8"))

llm = ChatOpenAI(
    model=os.environ.get("MINEAGENT_MODEL") or CFG.get("model", "deepseek-chat"),
    base_url=os.environ.get("MINEAGENT_BASE_URL") or CFG.get("base_url"),
    api_key=os.environ.get("MINEAGENT_API_KEY") or "EMPTY",
    temperature=CFG.get("temperature", 0.3),
)


class AgentState(TypedDict, total=False):
    data: Any
    route: str


'''

HEADERS = {
    "langchain": _HEADER_LANGCHAIN,
    "autogen": _HEADER_AUTOGEN,
    "crewai": _HEADER_CREWAI,
}

# 非 LangGraph 框架在通用 header 后面追加自己的 import 与客户端初始化。
# 节点块仍然用 langchain 的 @tool / create_agent / ChatPromptTemplate（它们是
# 框架无关的「步骤实现」），编排层才换成目标框架的原生对象。
_FRAMEWORK_HEADER_EXTRA = {
    "smolagents": '''
# ── smolagents：节点用 langchain 实现，编排与推理循环交给 smolagents ──
from smolagents import OpenAIServerModel, Tool, ToolCallingAgent

smol_model = OpenAIServerModel(
    model_id=os.environ.get("MINEAGENT_MODEL") or CFG.get("model", "gpt-4o-mini"),
    api_base=os.environ.get("MINEAGENT_BASE_URL") or CFG.get("base_url"),
    api_key=os.environ.get("MINEAGENT_API_KEY") or "EMPTY",
)


def as_smol_tool(lc_tool) -> Tool:
    """把 langchain 的 @tool 包成 smolagents 的 Tool。"""
    class _Wrap(Tool):
        name = getattr(lc_tool, "name", "tool")
        description = getattr(lc_tool, "description", "") or ""
        inputs = {"query": {"type": "string", "description": "工具参数"}}
        output_type = "string"

        def forward(self, query: str) -> str:
            return str(lc_tool.invoke(query))

    return _Wrap()
''',
    "agno": '''
# ── agno：节点用 langchain 实现，编排与推理交给 agno Agent ──
from agno.agent import Agent as AgnoAgent
from agno.models.openai import OpenAIChat

agno_model = OpenAIChat(
    id=os.environ.get("MINEAGENT_MODEL") or CFG.get("model", "gpt-4o-mini"),
    base_url=os.environ.get("MINEAGENT_BASE_URL") or CFG.get("base_url"),
    api_key=os.environ.get("MINEAGENT_API_KEY") or "EMPTY",
)


def as_agno_tool(lc_tool):
    """把 langchain 的 @tool 包成 agno 能用的普通函数（靠 docstring 描述）。"""
    def _call(query: str = "") -> str:
        return str(lc_tool.invoke(query))

    _call.__name__ = getattr(lc_tool, "name", "tool")
    _call.__doc__ = getattr(lc_tool, "description", "") or ""
    return _call
''',
    "openai_agents": '''
# ── OpenAI Agents SDK：节点用 langchain 实现，编排交给 Agent / Runner ──
# 用 OpenAIChatCompletionsModel 而不是默认的 Responses API：
# 绝大多数 OpenAI 兼容服务（含本地 vLLM / Ollama / 各家兼容网关）只实现
# /v1/chat/completions，走 Responses 会直接 404 或解析失败。
from agents import (Agent as OpenAIAgent, OpenAIChatCompletionsModel, Runner,
                    function_tool)
from openai import AsyncOpenAI

agent_client = AsyncOpenAI(
    base_url=os.environ.get("MINEAGENT_BASE_URL") or CFG.get("base_url"),
    api_key=os.environ.get("MINEAGENT_API_KEY") or "EMPTY",
)

agent_model = OpenAIChatCompletionsModel(
    model=os.environ.get("MINEAGENT_MODEL") or CFG.get("model", "gpt-4o-mini"),
    openai_client=agent_client,
)


def as_agent_tool(lc_tool):
    """把 langchain 的 @tool 包成 OpenAI Agents SDK 的 function_tool。"""
    def _run(query: str = "") -> str:
        return str(lc_tool.invoke(query))

    _run.__name__ = getattr(lc_tool, "name", "tool")
    _run.__doc__ = getattr(lc_tool, "description", "") or ""
    return function_tool(_run)
''',
    "semantic_kernel": '''
# ── Semantic Kernel：节点用 langchain 实现，编排交给 ChatCompletionAgent ──
import asyncio

from openai import AsyncOpenAI
from semantic_kernel import Kernel
from semantic_kernel.agents import ChatCompletionAgent
from semantic_kernel.connectors.ai.open_ai import OpenAIChatCompletion

sk_kernel = Kernel()
sk_kernel.add_service(OpenAIChatCompletion(
    ai_model_id=os.environ.get("MINEAGENT_MODEL") or CFG.get("model", "gpt-4o-mini"),
    async_client=AsyncOpenAI(
        base_url=os.environ.get("MINEAGENT_BASE_URL") or CFG.get("base_url"),
        api_key=os.environ.get("MINEAGENT_API_KEY") or "EMPTY",
    ),
))
''',
}


def _header_for(framework: str) -> str:
    """按框架拼 header：LangGraph 系用原样，其余去掉 StateGraph 再加自己的部分。"""
    if framework in _LANGGRAPH_FRAMEWORKS:
        return _HEADER_LANGCHAIN
    base = _HEADER_LANGCHAIN.replace(
        "from langgraph.graph import END, START, StateGraph\n", "")
    extra = _FRAMEWORK_HEADER_EXTRA.get(framework, "")
    if extra:
        anchor = 'CFG = json.loads((HERE / "config.json").read_text(encoding="utf-8"))\n'
        base = base.replace(anchor, anchor + extra, 1)
    return base


def _tool_ids(spec: Dict[str, Any]) -> set:
    return {n["id"] for n in spec["nodes"] if _kind_of(n) in TOOL_KINDS}


def _edge_into_graph(spec: Dict[str, Any]) -> List[Dict[str, Any]]:
    """把 tool 节点从图里"压缩"掉。

    tool 不是图里的执行步骤，而是被 agent 调用的函数。所以
    agent -> tool -> observation 要变成 agent -> observation。
    """
    tool_ids = _tool_ids(spec)
    edges = spec["edges"]
    by_source: Dict[str, List[Dict[str, Any]]] = {}
    for e in edges:
        by_source.setdefault(e["source"], []).append(e)

    def resolve(target: str, depth: int = 0) -> str | None:
        if target not in tool_ids:
            return target
        if depth > 8:
            return None
        for e in by_source.get(target, []):
            got = resolve(e["target"], depth + 1)
            if got:
                return got
        return None

    out: List[Dict[str, Any]] = []
    seen = set()
    for e in edges:
        if e["source"] in tool_ids:
            continue  # 从 tool 出的边不参与构图
        target = resolve(e["target"])
        if not target:
            continue
        key = (e["source"], target, e.get("sourceHandle") or "out")
        if key in seen:
            continue
        seen.add(key)
        out.append({**e, "target": target})
    return out


def _graph_section(spec: Dict[str, Any], framework: str) -> str:
    """图组装：节点、普通边、分支条件边、入口出口。"""
    nodes = {n["id"]: n for n in spec["nodes"]}
    order = topo_order(spec)
    graph_edges = _edge_into_graph(spec)
    lines: List[str] = []

    tool_names = [_pyid(nodes[i]["name"]) for i in order if _kind_of(nodes[i]) in TOOL_KINDS]
    if tool_names:
        lines.append("# 全量工具（手写代码里可以直接引用；agent 默认只拿自己下游那几个）")
        lines.append(f"TOOLS = [{', '.join(tool_names)}]")
        lines.append("")
    else:
        lines.append("TOOLS: list = []")
        lines.append("")

    # 每个 agent 只暴露它自己下游的工具：与预览执行器 runner.tools_for 同一套语义，
    # 避免「检索 agent 也能看见写库工具」这种越权
    agents_in_canvas = [nodes[i] for i in order if _kind_of(nodes[i]) in AGENT_KINDS]
    for a in agents_in_canvas:
        allowed = []
        for tid in _agent_tool_ids(spec, a["id"]):
            if tid in nodes:
                allowed.append(_pyid(nodes[tid]["name"]))
        lines.append(
            f"TOOLS_{_pyid(a['name'])} = [{', '.join(allowed)}]"
            f"  # {a.get('label') or a['name']} 可见的工具"
        )
    if agents_in_canvas:
        lines.append("")

    if framework in _LANGGRAPH_FRAMEWORKS:
        lines.append("builder = StateGraph(AgentState)")
        for nid in order:
            node = nodes[nid]
            fn = _pyid(node["name"])
            if _kind_of(node) in TOOL_KINDS:
                # 工具节点本身不是图里的执行步骤，工具在 agent 内部被调用
                continue
            p = node.get("params") or {}
            opts = {
                "timeout_s": _num(p, "timeout_s", 120),
                "max_retries": int(_num(p, "max_retries", 0)),
                "retry_backoff_s": _num(p, "retry_backoff_s", 2),
                "rate_per_minute": int(_num(p, "rate_per_minute", 0)),
                "on_error": _text(p, "on_error", "block"),
            }
            lines.append(
                f"builder.add_node({_q(node['name'])}, "
                f"_track({fn}, {_q(node['id'])}, {_q(node['name'])}, "
                f"{_q(node.get('label') or '')}, {_q(_kind_of(node))}, "
                f"{json.dumps(opts, ensure_ascii=False)}))"
            )
        lines.append("")

        # 普通边 / 条件边（tool 节点已被压缩掉）
        by_source: Dict[str, List[Dict[str, Any]]] = {}
        for e in graph_edges:
            by_source.setdefault(e["source"], []).append(e)

        entry = next((i for i in order if _kind_of(nodes[i]) == "input"), order[0] if order else None)
        if entry:
            lines.append(f"builder.add_edge(START, {_q(nodes[entry]['name'])})")

        for src in order:
            src_node = nodes[src]
            outs = by_source.get(src, [])
            if not outs:
                continue
            kind = _kind_of(src_node)
            err_outs = [e for e in outs if str(e.get("sourceHandle") or "") == "error"]
            normal_outs = [e for e in outs if str(e.get("sourceHandle") or "") != "error"]

            # 接了「错误出口」的普通节点：用 conditional edge 在 error / 正常之间分流
            if err_outs and kind not in ROUTE_KINDS and kind not in TOOL_KINDS \
                    and len(normal_outs) <= 1:
                err_target = nodes[err_outs[0]["target"]]["name"]
                out_target = nodes[normal_outs[0]["target"]]["name"] if normal_outs else "END"
                out_lit = out_target if out_target == "END" else _q(out_target)
                lines.append(
                    f"builder.add_conditional_edges(\n"
                    f"    {_q(src_node['name'])},\n"
                    f'    lambda s: "error" if s.get("__error__") else "out",\n'
                    f"    {{{_q('error')}: {_q(err_target)}, {_q('out')}: {out_lit}}},\n"
                    f")"
                )
                continue

            handles = {(e.get("sourceHandle") or "out") for e in normal_outs}
            # 同一端口接了多条边：这些是并行分支，必须全部连上，
            # 只取第一条会让下游节点变成孤岛（图跑不到终点）
            if len(normal_outs) > 1 and len(handles) == 1 and kind not in ROUTE_KINDS:
                for e in normal_outs:
                    target = nodes[e["target"]]["name"]
                    lines.append(f"builder.add_edge({_q(src_node['name'])}, {_q(target)})")
                continue

            multi = len(handles) > 1 or kind in ROUTE_KINDS
            if multi:
                mapping = {}
                for e in normal_outs:
                    h = e.get("sourceHandle") or "out"
                    mapping[h] = nodes[e["target"]]["name"]
                map_lit = ", ".join(f"{_q(k)}: {_q(v)}" for k, v in mapping.items())
                default = next(iter(mapping.values()))
                lines.append(
                    f"builder.add_conditional_edges(\n"
                    f"    {_q(src_node['name'])},\n"
                    f"    lambda s: s.get(\"route\") or \"{next(iter(mapping))}\",\n"
                    f"    {{{map_lit}}},\n"
                    f")"
                )
            else:
                target = nodes[normal_outs[0]["target"]]["name"]
                lines.append(f"builder.add_edge({_q(src_node['name'])}, {_q(target)})")

        # 没有出边的节点连到 END
        for nid in order:
            node = nodes[nid]
            if _kind_of(node) in TOOL_KINDS:
                continue
            if not by_source.get(nid):
                lines.append(f"builder.add_edge({_q(node['name'])}, END)")

        lines.append("")
        lines.append("")
        lines.append("def build_graph(checkpointer=None):")
        lines.append("    \"\"\"构建（可选带持久化 checkpointer 的）LangGraph 图，服务入口会复用。\"\"\"")
        lines.append("    return builder.compile(checkpointer=checkpointer)")
        lines.append("")
        lines.append("")
        lines.append("graph = build_graph()")
    elif framework == "smolagents":
        lines.append("# smolagents：每个 agent 节点变成一个 ToolCallingAgent，工具包成它的 Tool")
        agents = [nodes[i] for i in order
                  if _kind_of(nodes[i]) in ("agent", "worker", "supervisor")]
        if not agents:
            agents = [nodes[i] for i in order if _kind_of(nodes[i]) not in TOOL_KINDS][:1]
        for a in agents:
            fn = _pyid(a["name"])
            allowed = [_pyid(nodes[t]["name"]) for t in _agent_tool_ids(spec, a["id"])
                       if t in nodes]
            tools_expr = "[" + ", ".join(f"as_smol_tool({t})" for t in allowed) + "]"
            p = a.get("params") or {}
            max_steps = int(_num(p, "max_steps", 6))
            lines.append(
                f"{fn}_agent = ToolCallingAgent(\n"
                f"    tools={tools_expr},\n"
                f"    model=smol_model,\n"
                f"    max_steps={max_steps},\n"
                f"    instructions={_q(a.get('description') or a.get('label') or '')},\n"
                f")"
            )
        lines.append("")
        lines.append("_AGENTS = [" + ", ".join(
            f"{_pyid(a['name'])}_agent" for a in agents) + "]")
    elif framework == "agno":
        lines.append("# agno：每个 agent 节点变成一个 AgnoAgent")
        agents = [nodes[i] for i in order
                  if _kind_of(nodes[i]) in ("agent", "worker", "supervisor")]
        if not agents:
            agents = [nodes[i] for i in order if _kind_of(nodes[i]) not in TOOL_KINDS][:1]
        for a in agents:
            fn = _pyid(a["name"])
            allowed = [_pyid(nodes[t]["name"]) for t in _agent_tool_ids(spec, a["id"])
                       if t in nodes]
            tools_expr = "[" + ", ".join(f"as_agno_tool({t})" for t in allowed) + "]"
            lines.append(
                f"{fn}_agent = AgnoAgent(\n"
                f"    name={_q(a['name'])},\n"
                f"    model=agno_model,\n"
                f"    tools={tools_expr},\n"
                f"    instructions={_q(a.get('description') or a.get('label') or '')},\n"
                f"    markdown=False,\n"
                f")"
            )
        lines.append("")
        lines.append("_AGENTS = [" + ", ".join(
            f"{_pyid(a['name'])}_agent" for a in agents) + "]")
    elif framework == "openai_agents":
        lines.append("# OpenAI Agents SDK：每个 agent 节点变成一个 Agent")
        agents = [nodes[i] for i in order
                  if _kind_of(nodes[i]) in ("agent", "worker", "supervisor")]
        if not agents:
            agents = [nodes[i] for i in order if _kind_of(nodes[i]) not in TOOL_KINDS][:1]
        for a in agents:
            fn = _pyid(a["name"])
            allowed = [_pyid(nodes[t]["name"]) for t in _agent_tool_ids(spec, a["id"])
                       if t in nodes]
            tools_expr = "[" + ", ".join(f"as_agent_tool({t})" for t in allowed) + "]"
            lines.append(
                f"{fn}_agent = OpenAIAgent(\n"
                f"    name={_q(a['name'])},\n"
                f"    instructions={_q(a.get('description') or a.get('label') or '')},\n"
                f"    tools={tools_expr},\n"
                f"    model=agent_model,\n"
                f")"
            )
        lines.append("")
        lines.append("_AGENTS = [" + ", ".join(
            f"{_pyid(a['name'])}_agent" for a in agents) + "]")
    elif framework == "semantic_kernel":
        lines.append("# Semantic Kernel：每个 agent 节点变成一个 ChatCompletionAgent")
        agents = [nodes[i] for i in order
                  if _kind_of(nodes[i]) in ("agent", "worker", "supervisor")]
        if not agents:
            agents = [nodes[i] for i in order if _kind_of(nodes[i]) not in TOOL_KINDS][:1]
        for a in agents:
            fn = _pyid(a["name"])
            lines.append(
                f"{fn}_agent = ChatCompletionAgent(\n"
                f"    kernel=sk_kernel,\n"
                f"    name={_q(_ascii_id(a['name'], a['id']))},\n"
                f"    instructions={_q(a.get('description') or a.get('label') or '')},\n"
                f")"
            )
        lines.append("")
        lines.append("_AGENTS = [" + ", ".join(
            f"{_pyid(a['name'])}_agent" for a in agents) + "]")
    elif framework == "autogen":
        lines.append("# AutoGen：把画布里的 agent 节点变成 AssistantAgent，按对话推进")
        agents = [nodes[i] for i in order if _kind_of(nodes[i]) in ("agent", "worker", "supervisor")]
        if not agents:
            agents = [nodes[i] for i in order if _kind_of(nodes[i]) not in TOOL_KINDS][:1]
        for a in agents:
            fn = _pyid(a["name"])
            lines.append(
                f"{fn}_agent = AssistantAgent(\n"
                f"    name={_q(a['name'])},\n"
                f"    llm_config=llm_config,\n"
                f"    system_message={_q(a.get('description') or a.get('label') or '')},\n"
                f")"
            )
        lines.append("")
        lines.append("user_proxy = UserProxyAgent(name=\"user_proxy\", code_execution_config=False)")
        names = ", ".join(f"{_pyid(a['name'])}_agent" for a in agents)
        lines.append(f"groupchat = GroupChat(agents=[user_proxy, {names}], messages=[], max_round=12)")
        lines.append("manager = GroupChatManager(groupchat=groupchat, llm_config=llm_config)")
    else:
        lines.append("# CrewAI：把画布里的 agent 节点变成 CrewAI 的 Agent + Task")
        agents = [nodes[i] for i in order if _kind_of(nodes[i]) in ("agent", "worker", "supervisor")]
        if not agents:
            agents = [nodes[i] for i in order if _kind_of(nodes[i]) not in TOOL_KINDS][:1]
        for a in agents:
            fn = _pyid(a["name"])
            lines.append(
                f"{fn}_agent = Agent(\n"
                f"    role={_q(a.get('label') or a['name'])},\n"
                f"    goal={_q(a.get('description') or '完成任务')},\n"
                f"    backstory={_q(a.get('description') or '')},\n"
                f"    llm=llm,\n"
                f"    verbose=False,\n"
                f"    allow_delegation=False,\n"
                f")"
            )
        lines.append("")
        lines.append("_agents = [" + ", ".join(f"{_pyid(a['name'])}_agent" for a in agents) + "]")
        lines.append("tasks = [")
        for a in agents:
            fn = _pyid(a["name"])
            lines.append(
                f"    Task(description=\"{{input}}\", expected_output=\"完成的结果\", "
                f"agent={fn}_agent),"
            )
        lines.append("]")
        lines.append("crew = Crew(agents=_agents, tasks=tasks, process=Process.sequential, verbose=False)")

    return "\n".join(lines)


def _main_section(spec: Dict[str, Any], framework: str) -> str:
    order = topo_order(spec)
    nodes = {n["id"]: n for n in spec["nodes"]}
    entry = next((i for i in order if _kind_of(nodes[i]) == "input"), order[0] if order else None)
    entry_name = nodes[entry]["name"] if entry else "input"

    if framework in _LANGGRAPH_FRAMEWORKS:
        body = (
            f'    config = {{"configurable": {{"thread_id": thread_id}}}} if thread_id else {{}}\n'
            f'    result = graph.invoke({{"data": user_input, "user_input": user_input, "route": ""}},\n'
            f'                         config=config)\n'
            f'    data = result.get("data", "")\n'
            f'    _emit({{"event": "final", "output": data if isinstance(data, str) else _brief(data)}})\n'
            f'    return data\n'
        )
    elif framework == "smolagents":
        body = (
            f'    text = user_input\n'
            f'    for _ag in _AGENTS:\n'
            f'        _r = _ag.run(text)\n'
            f'        text = getattr(_r, "content", None) or str(_r)\n'
            f'    _emit({{"event": "final", "output": text}})\n'
            f'    return text\n'
        )
    elif framework == "agno":
        body = (
            f'    text = user_input\n'
            f'    for _ag in _AGENTS:\n'
            f'        _r = _ag.run(text)\n'
            f'        text = getattr(_r, "content", None) or str(_r)\n'
            f'    _emit({{"event": "final", "output": text}})\n'
            f'    return text\n'
        )
    elif framework == "openai_agents":
        body = (
            f'    text = user_input\n'
            f'    for _ag in _AGENTS:\n'
            f'        _r = Runner.run_sync(_ag, text)\n'
            f'        text = getattr(_r, "final_output", None) or str(_r)\n'
            f'    _emit({{"event": "final", "output": text}})\n'
            f'    return text\n'
        )
    elif framework == "semantic_kernel":
        body = (
            f'    async def _run_all(text: str) -> str:\n'
            f'        for _ag in _AGENTS:\n'
            f'            _last = ""\n'
            f'            async for _r in _ag.invoke(text):\n'
            f'                _last = str(_r)\n'
            f'            text = _last or text\n'
            f'        return text\n'
            f'    text = asyncio.run(_run_all(user_input))\n'
            f'    _emit({{"event": "final", "output": text}})\n'
            f'    return text\n'
        )
    elif framework == "autogen":
        body = (
            f'    user_proxy.initiate_chat(manager, message=user_input)\n'
            f'    return groupchat.messages[-1].get("content", "") if groupchat.messages else ""\n'
        )
    else:
        body = (
            f'    result = crew.kickoff(inputs={{"input": user_input}})\n'
            f'    return str(result)\n'
        )

    run_main = (
        'if __name__ == "__main__":\n'
        "    import argparse\n"
        "\n"
        "    parser = argparse.ArgumentParser(description=" + _q(spec["name"]) + ")\n"
        '    parser.add_argument("--input", "-i", default="", help="交给智能体的任务")\n'
        "    args = parser.parse_args()\n"
        "    text = args.input or input(\"请输入任务：\").strip()\n"
    )
    if framework in _LANGGRAPH_FRAMEWORKS:
        run_main += (
            "    try:\n"
            "        answer = main(text)\n"
            "    except Exception as exc:  # noqa: BLE001\n"
            '        _emit({"event": "run_end", "status": "error", "message": str(exc), "output": ""})\n'
            "        raise\n"
            "    print(\"\")\n"
            '    print("=" * 16, "最终结果", "=" * 16)\n'
            "    print(answer)\n"
            '    _emit({"event": "run_end", "status": "ok", "output": answer if isinstance(answer, str) else _brief(answer)})\n'
        )
    else:
        run_main += (
            "    answer = main(text)\n"
            "    print(\"\")\n"
            '    print("=" * 16, "最终结果", "=" * 16)\n'
            "    print(answer)\n"
        )

    return (
        "def main(user_input: str, thread_id: str = \"\") -> str:\n"
        f'    """入口：把用户输入交给 {entry_name}，一路跑完整张图。"""\n'
        f"{body}"
        "\n"
        "\n"
        f"{run_main}"
    )


def default_block(kind: str, label: str = "", description: str = "",
                  params: Dict[str, Any] | None = None,
                  name: str | None = None) -> str:
    """给某类节点生成一份默认的原生代码块（新增节点时直接用这个）。"""
    node = {
        "id": f"new_{kind}",
        "kind": kind,
        "name": name or f"{kind}_1",
        "label": label or kind,
        "description": description or "",
        "params": params or {},
        "model": None,
    }
    return node_block(node).strip()


def render_agent_full(spec: Dict[str, Any], framework: str) -> tuple:
    """生成完整的 agent.py，并返回每个节点对应的代码块。

    返回 (agent.py 全文, {node_id: 该节点的代码块})。
    节点块会被写回画布数据，网页上「代码逻辑」显示的就是这段。
    """
    # 用 replace 而不是 str.format：模板里现在有大量代码花括号
    header = _header_for(framework)
    header = header.replace("{framework_label}", str(spec.get("framework_label", framework)))
    header = header.replace("{name}", str(spec["name"]))
    order = topo_order(spec)
    nodes = {n["id"]: n for n in spec["nodes"]}

    blocks: List[str] = []
    blocks_by_id: Dict[str, str] = {}
    for nid in order:
        node = nodes[nid]
        custom = (node.get("code") or "").strip()
        # 用户手动改过（code_touched）并且是原生块格式 -> 保留他的版本
        if custom.startswith("#") and node.get("code_touched"):
            block = custom + "\n"
        else:
            block = node_block(node, spec)
        blocks.append(block)
        blocks_by_id[nid] = block.strip()

    graph_section = _graph_section(spec, framework)
    main_section = _main_section(spec, framework)

    parts = [
        header,
        "# ═══════════════════════════════════════════════════════════════\n"
        "# 节点实现：每个节点对应画布上的一个方块\n"
        "# ═══════════════════════════════════════════════════════════════\n",
        "\n".join(blocks),
        "\n# ═══════════════════════════════════════════════════════════════\n"
        "# 把节点组装成可执行的图\n"
        "# ═══════════════════════════════════════════════════════════════\n\n"
        + graph_section
        + "\n\n",
        "\n# ═══════════════════════════════════════════════════════════════\n"
        "# 命令行入口\n"
        "# ═══════════════════════════════════════════════════════════════\n"
        + main_section,
    ]
    return "".join(parts), blocks_by_id


def render_agent_py(spec: Dict[str, Any], framework: str) -> str:
    """生成完整的 agent.py（框架原生代码）。"""
    return render_agent_full(spec, framework)[0]
