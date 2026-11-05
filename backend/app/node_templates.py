"""每个节点类型的默认代码模板。

模板里的 `ctx` 是一个 runtime_sdk.NodeContext 实例，提供：
    ctx.text          上一节点输出转成的字符串
    ctx.input         上一节点输出的原始对象
    ctx.state         跨节点共享的可变字典
    ctx.params        节点参数（编辑面板里的 params）
    ctx.llm(...)      调用大模型，返回字符串
    ctx.llm_stream()  流式调用大模型
    ctx.agent(...)    内置 ReAct 工具循环
    ctx.json_prompt() 结构化输出，返回 dict
    ctx.http()        HTTP 请求
    ctx.search()      联网搜索
    ctx.skill()       读取 skills/*.md 或内联文本
    ctx.remember()/ctx.recall()/ctx.history()
    ctx.log()/ctx.emit()  日志与事件
"""
from __future__ import annotations

T = {}

T["input"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """入口：把用户输入交给下游。"""
    text = ctx.text.strip()
    if not text:
        raise ValueError("输入为空，请先在运行面板填写输入")
    ctx.log(f"收到输入：{len(text)} 字")
    return text
'''

T["output"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """出口：终止流程并返回最终答案给用户。"""
    answer = ctx.text
    ctx.emit("final", {"answer": answer})
    return answer
'''

T["llm"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """单次大模型推理。"""
    system = ctx.params.get("system") or "你是一个严谨的助手，回答要准确、可执行。"
    return ctx.llm(ctx.text, system=system)
'''

T["agent"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """自主 Agent：按节点属性里选定的推理模式执行。

    模式：react / plan_execute / goal / reflexion / tool_call / simple。
    画布中「连到本节点输入」的 tool 子图会自动注入 ctx.tools。
    如果这个 agent 配了下级，可以用 ctx.delegate(名字, 任务) 把活派出去。
    """
    system = ctx.params.get("system") or "你是一个能自主使用工具的智能体。"
    return ctx.agent(
        task=ctx.text,
        tools=ctx.tools,
        system=system,
        mode=ctx.params.get("mode", "react"),
        max_steps=ctx.params.get("max_steps", 6),
    )
'''

T["prompt"] = '''from runtime_sdk import NodeContext

TEMPLATE = ctx_params = """请基于以下内容完成任务。

---
{input}
---

要求：{requirement}
"""


def run(ctx: NodeContext):
    """提示词模板：用 {{input}} 之外的字段做拼接。"""
    requirement = ctx.params.get("requirement", "条理清晰，给出可执行步骤")
    return TEMPLATE.format(input=ctx.text, requirement=requirement)
'''

T["system_prompt"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """写入系统提示词，供下游 agent/llm 复用。"""
    persona = ctx.params.get("persona") or "你是资深行业专家，先给结论再给依据。"
    ctx.state["system_prompt"] = persona
    return ctx.text
'''

T["planner"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """任务规划：把目标拆成有序步骤。"""
    return ctx.llm(
        f"目标：{ctx.text}\\n\\n请输出执行计划，每行一步，形如「1. ...」，只输出计划。",
        system="你是任务规划专家，计划必须可执行、有依赖顺序。",
    )
'''

T["decomposer"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """任务分解：输出结构化子任务列表。"""
    data = ctx.json_prompt(
        "把任务拆成 2-6 个可并行或串行的子任务。",
        schema={"subtasks": [{"id": "s1", "title": "", "goal": ""}]},
        context=ctx.text,
    )
    return data
'''

T["router"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """条件路由：返回 "true" 或 "false" 决定走哪条出边。"""
    question = ctx.params.get("question") or "该请求是否需要调用工具？"
    verdict = ctx.llm(
        f"判别问题：{question}\\n待判内容：{ctx.text}\\n只回答 true 或 false。",
        system="你只输出 true 或 false，不要解释。",
    ).strip().lower()
    branch = "true" if verdict.startswith("true") else "false"
    ctx.emit("route", {"branch": branch})
    return branch
'''

T["reflector"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """反思：指出上一轮结果的不足并给出修正版。"""
    return ctx.llm(
        f"原始结果：\\n{ctx.text}\\n\\n请反思：1) 有无事实错误 2) 是否遗漏关键点 "
        "3) 如何改进。然后给出修订后的最终答案。",
        system="你是严格的自评审者。",
    )
'''

T["critic"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """评审：按评分标准打分并给出意见。"""
    return ctx.json_prompt(
        "评审以下产出，按维度打分并列出改进项。",
        schema={"score": 0, "dimensions": {"accuracy": 0, "completeness": 0, "clarity": 0},
                "issues": ["..."], "verdict": "pass|revise"},
        context=ctx.text,
    )
'''

T["self_check"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """自检：断言产出满足硬性约束。"""
    text = ctx.text
    checks = {
        "非空": len(text.strip()) > 0,
        "长度达标": len(text) >= ctx.params.get("min_len", 20),
        "无占位符": "TODO" not in text and "{input}" not in text,
    }
    failed = [k for k, ok in checks.items() if not ok]
    ctx.emit("self_check", {"passed": not failed, "failed": failed})
    if failed:
        ctx.log(f"自检未通过：{failed}，交由下游重试")
    return {"text": text, "passed": not failed, "failed": failed}
'''

T["evaluator"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """评估：给产出打 0-100 分，供循环节点判定是否继续迭代。"""
    data = ctx.json_prompt(
        "给产出质量打分（0-100），并说明扣分点。",
        schema={"score": 0, "reason": ""},
        context=ctx.text,
    )
    ctx.state["last_score"] = data.get("score", 0)
    return data
'''

T["tool"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext, **kwargs):
    """工具节点：被 agent 节点调用时 kwargs 为模型给出的参数。

    直接连在流程中时也会作为普通节点执行一次。
    """
    query = kwargs.get("query") or ctx.params.get("query") or ctx.text
    ctx.log(f"tool 执行：{query}")
    # TODO: 在这里写真正的工具逻辑
    return {"tool": ctx.params.get("name", "tool"), "query": query, "result": ""}
'''

T["function"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext, **kwargs):
    """自定义函数节点：写任意 Python 逻辑。"""
    payload = kwargs.get("payload", ctx.text)
    result = payload
    # TODO: 你的逻辑
    return result
'''

T["http_request"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """发起 HTTP 请求，返回 JSON。"""
    url = ctx.params.get("url") or "https://httpbin.org/get"
    method = (ctx.params.get("method") or "GET").upper()
    resp = ctx.http(method, url, params={"q": ctx.text} if method == "GET" else None,
                    json={"q": ctx.text} if method != "GET" else None)
    return resp
'''

T["web_search"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """联网搜索并摘要。"""
    hits = ctx.search(ctx.text)
    return ctx.llm(f"资料：\\n{hits}\\n\\n基于资料回答问题：{ctx.text}", system="只依据资料作答。")
'''

T["code_interpreter"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """在受限沙箱里执行一段 Python 代码（由模型生成或 params.code 指定）。"""
    code = ctx.params.get("code") or ctx.text
    out = ctx.exec_python(code)
    return {"code": code, "stdout": out.get("stdout", ""), "stderr": out.get("stderr", "")}
'''

T["shell"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """执行本地命令（默认拒绝，需在 params.allow=true 时放行）。"""
    if not ctx.params.get("allow", False):
        raise PermissionError("shell 节点默认禁用，请在节点参数里设置 allow=true")
    return ctx.shell(ctx.params.get("command") or ctx.text)
'''

T["file_io"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """读写项目工作目录下的文件。"""
    mode = ctx.params.get("mode", "read")
    path = ctx.params.get("path", "notes/output.txt")
    if mode == "write":
        return ctx.write_file(path, ctx.text)
    return ctx.read_file(path)
'''

T["sql_query"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """对 SQLite 数据库执行只读查询。"""
    sql = ctx.params.get("sql") or ctx.text
    rows = ctx.query_sql(sql)
    return rows
'''

T["rag_retriever"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """知识库检索：从 skills/ 或 docs/ 里做关键词+向量混合召回。"""
    hits = ctx.retrieve(ctx.text, top_k=ctx.params.get("top_k", 4))
    ctx.emit("retrieval", {"count": len(hits)})
    return {"query": ctx.text, "chunks": hits}
'''

T["embedding"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """文本向量化。"""
    return ctx.embed(ctx.text)
'''

T["vector_store"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """本地向量库读写（SQLite 存储，余弦相似度检索）。"""
    action = ctx.params.get("action", "search")
    if action == "upsert":
        return ctx.vector_upsert(ctx.text)
    return ctx.vector_search(ctx.text, top_k=ctx.params.get("top_k", 4))
'''

T["mcp_tool"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext, **kwargs):
    """调用一个 MCP 服务器暴露的工具。"""
    server = ctx.params.get("server", "http://127.0.0.1:3000")
    tool = ctx.params.get("tool", "search")
    args = kwargs or ctx.params.get("args", {"query": ctx.text})
    return ctx.mcp_call(server, tool, args)
'''

T["browser"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """抓取网页正文（无需浏览器内核，基于 HTTP + 正文抽取）。"""
    url = ctx.params.get("url") or ctx.text.strip()
    page = ctx.fetch_text(url)
    return ctx.llm(f"网页内容：\\n{page}\\n\\n请提炼要点。", system="只依据网页内容。")
'''

T["skill"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """技能节点。

    两种用法：
    1) params.skill_file = "report_writer.md"  → 读取项目 skills/ 下的技能文件
    2) 直接在本文件里写 SKILL_TEXT（粘贴 skill.md 全文）
    """
    body = ctx.skill(
        name=ctx.params.get("skill_file", ""),
        inline=ctx.params.get("skill_text", ""),
    )
    if ctx.params.get("pass_through"):
        return {"skill": body, "text": ctx.text}
    return ctx.llm(
        f"# 技能说明\\n{body}\\n\\n# 用户输入\\n{ctx.text}\\n\\n请按技能说明完成任务。",
        system="严格遵循技能说明的执行步骤。",
    )
'''

T["memory"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """记忆：短期（state）与长期（SQLite）读写。"""
    action = ctx.params.get("action", "write")
    key = ctx.params.get("key", "memory")
    if action == "read":
        return ctx.recall(key, "")
    ctx.remember(key, ctx.text, long_term=ctx.params.get("long_term", True))
    return ctx.text
'''

T["state_store"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """状态存取：把当前结果写入共享 state 的指定字段。"""
    key = ctx.params.get("key", "last_result")
    if ctx.params.get("mode") == "get":
        return ctx.state.get(key, "")
    ctx.state[key] = ctx.text
    return ctx.text
'''

T["blackboard"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """黑板：多智能体共享的事实板。"""
    board = ctx.state.setdefault("blackboard", [])
    entry = {"node": ctx.node_name, "content": ctx.text}
    board.append(entry)
    ctx.emit("blackboard", {"size": len(board)})
    return {"board": board, "latest": entry}
'''

T["history"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """会话历史：把本轮对话追加到历史并返回上下文。"""
    ctx.remember("conversation", ctx.text, long_term=True)
    turns = ctx.history("conversation")
    return {"history": turns, "latest": ctx.text}
'''

T["condition"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """条件判断：返回 "true" 或 "false"。"""
    expr = ctx.params.get("expr", "len(ctx.text) > 0")
    try:
        ok = bool(eval(expr, {"__builtins__": {}}, {"ctx": ctx, "text": ctx.text}))
    except Exception as exc:  # noqa: BLE001
        ctx.log(f"条件求值失败，默认走 false：{exc}")
        ok = False
    return "true" if ok else "false"
'''

T["loop"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """循环控制：返回 "loop" 继续回边，或 "exit" 结束循环。"""
    max_round = ctx.params.get("max_round", 3)
    round_no = ctx.state.get("loop_round", 0) + 1
    ctx.state["loop_round"] = round_no
    score = ctx.state.get("last_score", 0)
    need_more = round_no < max_round and score < ctx.params.get("pass_score", 80)
    ctx.emit("loop", {"round": round_no, "score": score, "continue": need_more})
    return "loop" if need_more else "exit"
'''

T["join"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """汇聚：合并多个分支的产出。"""
    merged = ctx.state.setdefault("join_buffer", {})
    merged[ctx.node_id] = ctx.input
    if ctx.params.get("strategy") == "concat":
        return "\\n\\n".join(str(v) for v in merged.values())
    return merged
'''

T["delay"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """延时（限流/退避用）。"""
    ctx.sleep(ctx.params.get("seconds", 1))
    return ctx.text
'''

T["subgraph"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """子图：把任务委派给 projects/ 下的另一个画布项目。"""
    target = ctx.params.get("project", "")
    if not target:
        raise ValueError("subgraph 需要指定 params.project（另一个画布的项目目录名）")
    return ctx.run_subgraph(target, ctx.text)
'''

T["human_approval"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """人工审批：无交互环境下按 params.default 自动放行或拒绝。"""
    decision = ctx.ask_human(ctx.text, default=ctx.params.get("default", "approve"))
    ctx.emit("approval", {"decision": decision})
    return {"text": ctx.text, "approved": decision == "approve"}
'''

T["guardrail"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """护栏：拦截敏感内容与越权动作。"""
    text = ctx.text
    banned = ctx.params.get("banned", ["rm -rf", "DROP TABLE", "sk-"])
    hit = [b for b in banned if b and b in text]
    if hit:
        ctx.emit("guardrail", {"blocked": True, "hit": hit})
        raise PermissionError(f"护栏拦截：命中 {hit}")
    return text
'''

T["observation"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """观察：记录本轮动作的真实结果（工具返回 / 环境反馈）。"""
    obs = {
        "node": ctx.node_name,
        "input": ctx.input,
        "summary": ctx.llm(
            f"把工具返回结果压缩成 3 条以内的观察要点：\\n{ctx.text}",
            system="只陈述事实，不推断。",
        ),
        "raw": ctx.text,
    }
    ctx.state.setdefault("observations", []).append(obs)
    ctx.emit("observation", {"summary": obs["summary"]})
    return obs
'''

T["review_observation"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """观察复核：判断观察是否充分、可信，是否需要再执行一次。"""
    data = ctx.json_prompt(
        "复核下面的观察结果：是否足够支撑决策？是否与目标相关？是否可信？",
        schema={"sufficient": True, "reliable": True, "missing": ["..."],
                "next_action": "continue|retry|replan", "reason": ""},
        context=ctx.input,
    )
    ctx.state["review"] = data
    ctx.emit("review_observation", data)
    return data
'''

T["format_observations"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """观察格式化：把多轮观察整理成结构化上下文。"""
    obs = ctx.state.get("observations", [])
    if not obs and isinstance(ctx.input, list):
        obs = ctx.input
    lines = []
    for i, item in enumerate(obs, 1):
        summary = item.get("summary") if isinstance(item, dict) else str(item)
        lines.append(f"{i}. {summary}")
    text = ctx.params.get("header", "## 已有观察\\n") + "\\n".join(lines)
    return {"formatted": text, "count": len(lines), "raw": obs}
'''

T["error_handler"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """错误处理：捕获上游异常并给出兜底动作。"""
    err = ctx.state.get("last_error")
    if not err:
        return ctx.text
    ctx.log(f"捕获错误：{err}")
    return ctx.llm(
        f"执行出错：{err}\\n原始输入：{ctx.text}\\n请给出修复步骤或替代方案。",
        system="你是故障排查专家。",
    )
'''

T["retry"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """重试：对当前结果做一次带反馈的修正重试。"""
    attempts = ctx.state.get("retry_attempt", 0) + 1
    ctx.state["retry_attempt"] = attempts
    ctx.emit("retry", {"attempt": attempts})
    return ctx.llm(
        f"上一次产出：\\n{ctx.text}\\n\\n它未通过校验（{ctx.state.get('review', {})}）。"
        f"请修正后重新输出完整结果（第 {attempts} 次尝试）。",
        system="你只输出修正后的完整结果。",
    )
'''

T["fallback"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """兜底：主路径失败时返回保底答案。"""
    ctx.log("进入兜底路径")
    return ctx.params.get("message") or "抱歉，当前任务未能完成，请补充信息后重试。"
'''

T["supervisor"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """主管：按画布上配置的组织关系，把任务分派给下级 agent，再汇总结果。

    下级来自节点属性里的「下级 agent」；没配就回退到 params.workers。
    """
    names = ctx.subordinates or ctx.params.get("workers", [])
    if not names:
        return ctx.agent(task=ctx.text, tools=ctx.tools,
                         mode=ctx.params.get("mode", "react"),
                         max_steps=ctx.params.get("max_steps", 6))
    results = {}
    for name in names:
        ctx.log(f"分派给下级：{name}")
        results[name] = ctx.delegate(name, ctx.text)
    summary = "\\n\\n".join(f"### {k}\\n{v}" for k, v in results.items())
    return ctx.llm(
        f"原始任务：{ctx.text}\\n\\n各下级的结果：\\n{summary}\\n\\n请汇总输出最终答案。",
        system="你是主管，只输出整合后的结论。",
    )
'''

T["worker"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """工作者：执行被分派的子任务。"""
    role = ctx.params.get("role", "通用执行者")
    task = ctx.input.get("subtask") if isinstance(ctx.input, dict) else ctx.text
    system = f"你的角色：{role}。只完成分配给你的子任务，结论要具体。"
    return ctx.agent(
        task=task,
        tools=ctx.tools,
        system=system,
        mode=ctx.params.get("mode", "react"),
        max_steps=ctx.params.get("max_steps", 4),
    )
'''

T["group_chat"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """群聊：多角色围绕议题轮流发言，主持人汇总。"""
    rounds = ctx.params.get("rounds", 2)
    topic = ctx.text
    transcript = []
    for r in range(rounds):
        reply = ctx.llm(f"议题：{topic}\\n已有发言：{transcript}\\n请以第 {r + 1} 轮身份发言。",
                        system="你只发一次言，观点明确，不重复他人。")
        transcript.append(reply)
    return ctx.llm(f"议题：{topic}\\n讨论记录：{transcript}\\n\\n输出最终共识。",
                   system="你是主持人，只输出结论。")
'''

T["handoff"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """转交：把上下文交给下游专门的 agent。"""
    return {"handoff_to": ctx.params.get("target", "specialist"),
            "reason": ctx.params.get("reason", "该任务超出当前角色能力"),
            "context": ctx.text}
'''

T["debate"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """辩论：正反双方各陈述一次，裁判裁决。"""
    topic = ctx.text
    pro = ctx.llm(f"议题：{topic}\\n请以支持方身份陈述理由。", system="你只输出支持方论点。")
    con = ctx.llm(f"议题：{topic}\\n请以反对方身份陈述理由。", system="你只输出反对方论点。")
    verdict = ctx.llm(f"支持方：{pro}\\n反对方：{con}\\n请裁决并给结论。", system="你是中立裁判。")
    return {"pro": pro, "con": con, "verdict": verdict}
'''

T["message_bus"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """消息总线：向频道广播消息，并返回频道内的消息。"""
    channel = ctx.params.get("channel", "default")
    bus = ctx.state.setdefault("bus", {}).setdefault(channel, [])
    bus.append({"from": ctx.node_name, "content": ctx.text})
    return {"channel": channel, "messages": bus[-10:]}
'''

T["formatter"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """格式化：把结果整理成指定格式（markdown / json / table）。"""
    fmt = ctx.params.get("format", "markdown")
    return ctx.llm(
        f"把下面内容转成 {fmt} 格式，只输出结果本身：\\n{ctx.text}",
        system="你是格式化工具，不做内容增删。",
    )
'''

T["parser"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """解析：从自由文本中抽取结构化字段。"""
    return ctx.json_prompt(
        "抽取字段，缺省用空字符串。",
        schema=ctx.params.get("schema", {"title": "", "items": ["..."], "summary": ""}),
        context=ctx.text,
    )
'''

T["summarizer"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """摘要：按目标长度压缩内容。"""
    limit = ctx.params.get("max_chars", 300)
    return ctx.llm(f"用不超过 {limit} 字概括要点：\\n{ctx.text}", system="只输出摘要正文。")
'''

T["validator"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """校验：按给定 schema 校验结构，不通过则抛出异常。"""
    schema = ctx.params.get("schema", {})
    data = ctx.input
    errors = ctx.validate(data, schema)
    ctx.emit("validation", {"ok": not errors, "errors": errors})
    if errors:
        raise ValueError(f"结构校验失败：{errors}")
    return data
'''

T["artifact_writer"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """产物写出：把结果保存到项目 outputs/ 目录。"""
    name = ctx.params.get("filename", "artifact.md")
    path = ctx.write_file(f"outputs/{name}", ctx.text)
    return {"path": path, "content": ctx.text}
'''

T["notification"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """通知：把结果推送到 webhook / 日志。"""
    webhook = ctx.params.get("webhook", "")
    if webhook:
        ctx.http("POST", webhook, json={"text": ctx.text})
    ctx.log("通知已发送")
    return ctx.text
'''

T["langgraph_state"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """LangGraph State 定义：声明图状态字段。"""
    fields = ctx.params.get("fields", ["messages", "next"])
    ctx.state.setdefault("langgraph_state", {f: None for f in fields})
    return ctx.text
'''

T["langgraph_node"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """LangGraph 节点：一个 state -> state 的函数。"""
    state = ctx.state.setdefault("langgraph_state", {})
    state[ctx.params.get("field", "messages")] = ctx.text
    return state
'''

T["langgraph_edge"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """LangGraph 边：声明转移关系。"""
    edge = ctx.params.get("edge", {"from": "START", "to": "END"})
    ctx.state.setdefault("langgraph_edges", []).append(edge)
    return ctx.text
'''

T["autogen_assistant"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """AutoGen AssistantAgent。"""
    return ctx.autogen_assistant(
        name=ctx.params.get("agent_name", "assistant"),
        system_message=ctx.params.get("system_message", "你是乐于助人的 AI 助手。"),
        task=ctx.text,
    )
'''

T["autogen_user_proxy"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """AutoGen UserProxyAgent（可执行代码的可信代理）。"""
    return ctx.autogen_user_proxy(
        name=ctx.params.get("agent_name", "user_proxy"),
        task=ctx.text,
        human_input_mode=ctx.params.get("human_input_mode", "NEVER"),
    )
'''

T["autogen_group_chat"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """AutoGen GroupChat：多 agent 轮询讨论。"""
    return ctx.autogen_group_chat(
        agents=ctx.params.get("agents", ["planner", "coder", "reviewer"]),
        task=ctx.text,
        max_round=ctx.params.get("max_round", 6),
    )
'''

T["autogen_tool_agent"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """AutoGen 带工具的 AssistantAgent。"""
    return ctx.agent(task=ctx.text, tools=ctx.tools,
                     system=ctx.params.get("system_message", "你是会使用工具的助手。"),
                     max_steps=ctx.params.get("max_steps", 6))
'''

T["crewai_agent"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """CrewAI Agent 定义。"""
    return ctx.crewai_agent(
        role=ctx.params.get("role", "研究员"),
        goal=ctx.params.get("goal", "收集并验证事实"),
        backstory=ctx.params.get("backstory", "你擅长快速梳理信息。"),
        task=ctx.text,
    )
'''

T["crewai_task"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """CrewAI Task 定义。"""
    return ctx.crewai_task(
        description=ctx.params.get("description") or ctx.text,
        expected_output=ctx.params.get("expected_output", "结构化的分析结论"),
        agent=ctx.params.get("agent", ""),
    )
'''

T["crewai_crew"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """CrewAI Crew：把多个 agent 与 task 组装成团队。"""
    return ctx.crewai_crew(
        agents=ctx.params.get("agents", []),
        tasks=ctx.params.get("tasks", []),
        process=ctx.params.get("process", "sequential"),
        task=ctx.text,
    )
'''

T["crewai_tool"] = '''from runtime_sdk import NodeContext


def run(ctx: NodeContext, **kwargs):
    """CrewAI Tool 包装。"""
    return ctx.crewai_tool(
        name=ctx.params.get("name", "search_tool"),
        description=ctx.params.get("description", "搜索资料"),
        payload=kwargs or {"query": ctx.text},
    )
'''

CODE_TEMPLATES = T
