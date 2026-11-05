"""把画布编译成一份真正的框架原生代码（agent.py）。

设计原则：**代码是主体，画布节点是它的视图**。
每个节点对应 agent.py 里一个带 ═══ 标记的代码块，块里是这个节点真正的框架写法
（@tool / create_react_agent / ChatPromptTemplate + llm.invoke …），而不是对某个
通用执行器的调用。生成结果应该一眼能看出这是一个标准 LangGraph / AutoGen / CrewAI 项目。
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

ROUTE_KINDS = {"router", "condition", "branch", "switch"}
TOOL_KINDS = {
    "tool", "function", "mcp_tool", "crewai_tool", "http_request", "web_search",
    "code_interpreter", "sql_query", "rag_retriever", "file_io", "browser", "shell",
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


def _pyid(name: str) -> str:
    """把节点名变成合法的 Python 标识符。"""
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
        body = (
            '    import sqlite3\n'
            '    conn = sqlite3.connect(query)\n'
            '    try:\n'
            '        cur = conn.execute(sql)\n'
            '        return str(cur.fetchall()[:50])\n'
            '    finally:\n'
            '        conn.close()\n'
        )
        arg = "sql: str"
        return (
            f"@tool\n"
            f"def {fn}({arg}) -> str:\n"
            f'    """{desc}"""\n'
            f"    raise ValueError(\"请在运行时传入数据库路径，或改用 ctx.exec_sql\")\n"
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


def _block_agent(node: Dict[str, Any]) -> str:
    fn = _pyid(node["name"])
    p = _params(node)
    mode = _text(p, "mode", "react")
    max_steps = int(_num(p, "max_steps", 6))
    system = _text(p, "system_prompt") or (
        "你是一个能调用工具的智能体。回答前先想清楚需要哪些信息，"
        "必要时调用工具，最后给出最终答案。"
    )
    return (
        f"def {fn}(state: AgentState) -> dict:\n"
        f'    """{node.get("label") or "Agent"} —— 推理模式：{mode}，最多 {max_steps} 步。"""\n'
        f'    task = state.get("data", "")\n'
        f'    origin = state.get("user_input", "")\n'
        f"    if origin and origin != task:\n"
        f'        task = f"{{origin}}\\n\\n## 上一轮观察 / 反馈\\n{{task}}\\n\\n请结合原始问题作答。"\n'
        f"    agent = create_agent(\n"
        f"        model={_llm_var(node)},\n"
        f"        tools=TOOLS,\n"
        f"        system_prompt={_q(system)},\n"
        f"    )\n"
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
    max_loops = int(_num(p, "max_loops", 0))
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
        f'    if branch == "false" and rounds > max_loops:\n'
        f'        branch = "true"\n'
        f'        _emit({{"event": "log", "level": "warn", "node": {nid}, "name": {name},\n'
        f'               "message": f"已到循环上限 {{max_loops}} 次，强制收敛"}})\n'
        f'    _emit({{"event": "route", "node": {nid}, "name": {name},\n'
        f'           "branch": branch, "reason": _brief(verdict, 120)}})\n'
        f'    return {{"data": text, "route": branch, "loop_count": rounds}}\n'
    )


def _block_retriever(node: Dict[str, Any]) -> str:
    fn = _pyid(node["name"])
    p = _params(node)
    top_k = int(_num(p, "top_k", 4))
    return (
        f"def {fn}(state: AgentState) -> dict:\n"
        f'    """{node.get("label") or "检索"} —— 从向量库取回最相关的片段。"""\n'
        f"    # 需要的话在这里初始化你的向量库，例如：\n"
        f"    #   from langchain_chroma import Chroma\n"
        f"    #   vectorstore = Chroma(persist_directory=\".store\", embedding_function=embeddings)\n"
        f"    #   retriever = vectorstore.as_retriever(search_kwargs={{\"k\": {top_k}}})\n"
        f"    query = state.get(\"data\", \"\")\n"
        f"    docs = []  # retriever.invoke(query)\n"
        f"    context = \"\\n\\n\".join(getattr(d, \"page_content\", str(d)) for d in docs)\n"
        f'    return {{"data": context or query}}\n'
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


def node_block(node: Dict[str, Any]) -> str:
    """生成单个节点在 agent.py 里的代码块。"""
    kind = _kind_of(node)
    header = _block_header(node)
    decl = _llm_decl(node)

    if kind == "input":
        body = _block_input(node)
    elif kind == "output":
        body = _block_output(node)
    elif kind in TOOL_KINDS:
        body = _block_tool(node)
    elif kind in ROUTE_KINDS:
        body = _block_router(node)
    elif kind in ("retriever", "vector_retriever", "rag"):
        body = _block_retriever(node)
    elif kind in ("memory", "conversation_memory"):
        body = _block_memory(node)
    elif kind == "agent" or kind in ("supervisor", "worker", "autogen_assistant",
                                     "crewai_agent", "group_chat", "debate"):
        body = _block_agent(node)
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

import json
import os
import time
from pathlib import Path
from typing import Any, TypedDict

from langchain.agents import create_agent
from langchain_core.prompts import ChatPromptTemplate, PromptTemplate
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph

HERE = Path(__file__).resolve().parent
CFG = json.loads((HERE / "config.json").read_text(encoding="utf-8"))

# ── 模型：key 从环境变量或 .env 读，不写死在代码里 ──────────────
llm = ChatOpenAI(
    model=os.environ.get("MINEAGENT_MODEL") or CFG.get("model", "deepseek-chat"),
    base_url=os.environ.get("MINEAGENT_BASE_URL") or CFG.get("base_url"),
    api_key=os.environ.get("MINEAGENT_API_KEY") or "EMPTY",
    temperature=CFG.get("temperature", 0.3),
    max_tokens=CFG.get("max_tokens", 2048),
)

# ── 运行事件：每个节点执行前后的输入/输出都回传给网页运行面板 ──────
EVENT_PREFIX = "@@EVENT@@"


def _emit(event: dict) -> None:
    try:
        print(EVENT_PREFIX + json.dumps(event, ensure_ascii=False, default=str), flush=True)
    except Exception:  # noqa: BLE001
        pass


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
    try:
        for chunk in model.stream(messages):
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


def _track(fn, node_id: str, name: str = "", label: str = "", kind: str = "llm"):
    """包一层：把节点执行前后的状态推给运行面板，并累计执行轨迹 trace。"""

    def wrapped(state):
        started = time.time()
        _emit({"event": "node_start", "node": node_id, "name": name or node_id,
               "label": label, "kind": kind})
        try:
            out = fn(state)
        except Exception as exc:  # noqa: BLE001
            _emit({"event": "error", "node": node_id, "name": name or node_id,
                   "message": str(exc)})
            raise
        data = out.get("data", "") if isinstance(out, dict) else out
        trace = list(state.get("trace") or [])
        trace.append({"node": name or node_id, "id": node_id, "kind": kind,
                      "output": _brief(data)})
        _emit({"event": "node_end", "node": node_id, "name": name or node_id, "kind": kind,
               "duration_ms": int((time.time() - started) * 1000),
               "output": _brief(data)})
        if isinstance(out, dict):
            out["trace"] = trace[-40:]
        return out

    return wrapped


class AgentState(TypedDict, total=False):
    """整张图共享的状态：data 在节点之间流动，route 承载分支信号。"""

    data: Any
    route: str
    history: list
    trace: list
    answer: Any
    loop_count: int
    user_input: str


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
from typing import Any, TypedDict

from autogen import AssistantAgent, GroupChat, GroupChatManager, UserProxyAgent
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
from typing import Any, TypedDict

from crewai import Agent, Crew, Process, Task
from crewai.tools import tool
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
        lines.append("# 所有工具节点汇总（agent 节点会用到）")
        lines.append(f"TOOLS = [{', '.join(tool_names)}]")
        lines.append("")
    else:
        lines.append("TOOLS: list = []")
        lines.append("")

    if framework == "langchain":
        lines.append("builder = StateGraph(AgentState)")
        for nid in order:
            node = nodes[nid]
            fn = _pyid(node["name"])
            if _kind_of(node) in TOOL_KINDS:
                # 工具节点本身不是图里的执行步骤，工具在 agent 内部被调用
                continue
            lines.append(
                f"builder.add_node({_q(node['name'])}, "
                f"_track({fn}, {_q(node['id'])}, {_q(node['name'])}, "
                f"{_q(node.get('label') or '')}, {_q(_kind_of(node))}))"
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
            handles = {(e.get("sourceHandle") or "out") for e in outs}
            multi = len(handles) > 1 or _kind_of(src_node) in ROUTE_KINDS
            if multi:
                mapping = {}
                for e in outs:
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
                target = nodes[outs[0]["target"]]["name"]
                lines.append(f"builder.add_edge({_q(src_node['name'])}, {_q(target)})")

        # 没有出边的节点连到 END
        for nid in order:
            node = nodes[nid]
            if _kind_of(node) in TOOL_KINDS:
                continue
            if not by_source.get(nid):
                lines.append(f"builder.add_edge({_q(node['name'])}, END)")

        lines.append("")
        lines.append("graph = builder.compile()")
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

    if framework == "langchain":
        body = (
            f'    result = graph.invoke({{"data": user_input, "user_input": user_input, "route": ""}})\n'
            f'    data = result.get("data", "")\n'
            f'    _emit({{"event": "final", "output": data if isinstance(data, str) else _brief(data)}})\n'
            f'    return data\n'
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
    if framework == "langchain":
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
        "def main(user_input: str) -> str:\n"
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
    header = HEADERS.get(framework, _HEADER_LANGCHAIN)
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
            block = node_block(node)
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
