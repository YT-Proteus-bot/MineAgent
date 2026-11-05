"""节点类型注册表：工业级 Agent 编排里会出现的节点全集。

前端「右键画布新增节点」的菜单、节点面板、默认代码模板都由这里驱动。
新增节点只需要在下面加一行。
"""
from __future__ import annotations

from typing import Any, Dict, List

from .node_templates import CODE_TEMPLATES

# 分类：id, 名称, 颜色
CATEGORIES: List[Dict[str, str]] = [
    {"id": "io", "label": "输入输出", "color": "#22d3ee"},
    {"id": "llm", "label": "推理与决策", "color": "#8b5cf6"},
    {"id": "tool", "label": "工具与能力", "color": "#f59e0b"},
    {"id": "memory", "label": "记忆与状态", "color": "#10b981"},
    {"id": "flow", "label": "流程控制", "color": "#64748b"},
    {"id": "observe", "label": "观察与反馈", "color": "#ef4444"},
    {"id": "collab", "label": "多智能体协作", "color": "#ec4899"},
    {"id": "post", "label": "后处理与交付", "color": "#3b82f6"},
    {"id": "fw", "label": "框架专有", "color": "#14b8a6"},
]

_CAT_COLOR = {c["id"]: c["color"] for c in CATEGORIES}


def P(key: str, label: str, default=None, placeholder: str = "",
      options=None, help_text: str = "") -> Dict[str, Any]:
    """参数定义。带 options 的会渲染成下拉框。"""
    item: Dict[str, Any] = {
        "key": key, "label": label, "default": default, "placeholder": placeholder,
    }
    if options:
        item["options"] = options
    if help_text:
        item["help"] = help_text
    return item


# Agent 的推理模式：每个 agent 节点可以单独选
AGENT_MODES: List[Dict[str, str]] = [
    {"value": "react", "label": "ReAct 循环",
     "desc": "思考 → 调工具 → 观察，反复循环直到能给出答案"},
    {"value": "plan_execute", "label": "Plan-and-Execute",
     "desc": "先让模型列一份执行计划，再逐步执行，适合多步任务"},
    {"value": "goal", "label": "Goal-driven 目标驱动",
     "desc": "围绕一个明确目标反复推进，自评达成度，未达成就继续"},
    {"value": "reflexion", "label": "Reflexion 反思重试",
     "desc": "先执行一版，再自我批判并重写，适合对质量要求高的产出"},
    {"value": "tool_call", "label": "Tool Calling 单轮调用",
     "desc": "只做一轮工具调用，快、便宜，适合确定性任务"},
    {"value": "simple", "label": "Simple 单次推理",
     "desc": "不循环、不用工具，直接一次大模型调用"},
]

_MODE_OPTIONS = [{"value": m["value"], "label": m["label"]} for m in AGENT_MODES]

# (kind, label, category, icon, description, outputs, params, language)
_DEFS: List[tuple] = [
    # ---------------- 输入输出 ----------------
    ("input", "输入 Input", "io", "▶", "每个智能体必须有的入口方块，接收用户输入。", ["out"], [], "python"),
    ("output", "输出 Output", "io", "■", "每个智能体必须有的出口方块，返回最终答案。", ["out"], [], "python"),

    # ---------------- 推理与决策 ----------------
    ("llm", "LLM 推理", "llm", "✦", "一次大模型调用，最基础的推理单元。", ["out"], [P("system", "系统提示", "")], "python"),
    ("agent", "Agent 主体", "llm", "◈", "自主 Agent，可选 ReAct / Plan / Goal 等推理模式；连到它的 tool 子图会自动注入工具。", ["out"],
     [P("mode", "推理模式", "react", options=_MODE_OPTIONS),
      P("system", "系统提示", ""), P("max_steps", "最大步数", 6)], "python"),
    ("prompt", "提示词模板", "llm", "❝", "把上游内容套进模板，做提示词工程。", ["out"], [P("requirement", "额外要求", "")], "python"),
    ("system_prompt", "系统提示词", "llm", "☰", "注入角色设定，供下游 agent/llm 复用。", ["out"], [P("persona", "角色设定", "")], "python"),
    ("planner", "任务规划", "llm", "◇", "把目标拆成有序执行计划。", ["out"], [], "python"),
    ("decomposer", "任务分解", "llm", "⋔", "输出结构化子任务列表，便于并行或分派。", ["out"], [], "python"),
    ("router", "条件路由", "llm", "⑂", "判断后走 true / false 两条出边，是分支与循环的枢纽。", ["true", "false"], [], "python"),
    ("reflector", "反思 Reflection", "llm", "↺", "对上一轮结果自我批判并给出修订版。", ["out"], [], "python"),
    ("critic", "评审 Critic", "llm", "⚖", "按维度打分并给改进项。", ["out"], [], "python"),
    ("self_check", "自检 Self-Check", "llm", "✓", "断言产出满足硬性约束。", ["out"], [P("min_len", "最小长度", 20)], "python"),
    ("evaluator", "质量评估", "llm", "◷", "给产出打 0-100 分，驱动循环是否继续。", ["out"], [], "python"),

    # ---------------- 工具与能力 ----------------
    ("tool", "工具 Tool", "tool", "⚙", "工具的通用节点，被 Agent 调用或直接执行。", ["out"],
     [P("name", "工具名", "tool"), P("query", "默认参数", "")], "python"),
    ("function", "自定义函数", "tool", "ƒ", "写任意 Python 逻辑的节点。", ["out"], [], "python"),
    ("http_request", "HTTP 请求", "tool", "↗", "调用外部 REST 接口。", ["out"],
     [P("url", "URL", "https://httpbin.org/get"), P("method", "方法", "GET")], "python"),
    ("web_search", "联网搜索", "tool", "⌕", "搜索并基于资料作答。", ["out"], [], "python"),
    ("code_interpreter", "代码解释器", "tool", "⌨", "在受限沙箱里执行 Python。", ["out"], [P("code", "预置代码", "")], "python"),
    ("shell", "命令执行", "tool", "$", "执行本地命令，默认禁用需显式放行。", ["out"],
     [P("command", "命令", ""), P("allow", "允许执行", False)], "python"),
    ("file_io", "文件读写", "tool", "▤", "读写项目工作目录下的文件。", ["out"],
     [P("mode", "模式(read/write)", "read"), P("path", "路径", "outputs/note.md")], "python"),
    ("sql_query", "SQL 查询", "tool", "▦", "对 SQLite 执行只读查询。", ["out"], [P("sql", "SQL", "")], "python"),
    ("rag_retriever", "知识库检索", "tool", "◎", "从 skills/ 与 docs/ 做混合召回。", ["out"], [P("top_k", "召回条数", 4)], "python"),
    ("embedding", "向量化", "tool", "⋯", "把文本转成向量。", ["out"], [], "python"),
    ("vector_store", "向量库", "tool", "◫", "本地向量库的写入与检索。", ["out"],
     [P("action", "动作(search/upsert)", "search"), P("top_k", "条数", 4)], "python"),
    ("mcp_tool", "MCP 工具", "tool", "◌", "调用 MCP 服务器暴露的工具。", ["out"],
     [P("server", "服务地址", ""), P("tool", "工具名", "")], "python"),
    ("browser", "网页抓取", "tool", "◍", "抓取网页正文并提炼要点。", ["out"], [P("url", "URL", "")], "python"),
    ("skill", "技能 Skill", "tool", "★", "贴入 skill.md 全文，或填写 skills/ 下的文件名。", ["out"],
     [P("skill_file", "技能文件名", "", "如 report_writer.md"), P("skill_text", "技能内容", ""),
      P("pass_through", "只透传不调用模型", False)], "markdown"),

    # ---------------- 记忆与状态 ----------------
    ("memory", "记忆 Memory", "memory", "◘", "短期(state)与长期(SQLite)记忆读写。", ["out"],
     [P("action", "动作(read/write)", "write"), P("key", "键", "memory"), P("long_term", "长期存储", True)], "python"),
    ("state_store", "状态存取", "memory", "▣", "写入或读取共享 state 字段。", ["out"],
     [P("key", "字段", "last_result"), P("mode", "模式(set/get)", "set")], "python"),
    ("blackboard", "黑板", "memory", "▩", "多智能体共享的事实板。", ["out"], [], "python"),
    ("history", "会话历史", "memory", "☷", "追加对话历史并返回上下文。", ["out"], [], "python"),

    # ---------------- 流程控制 ----------------
    ("condition", "条件判断", "flow", "?", "用表达式判定 true/false 两条出边。", ["true", "false"],
     [P("expr", "表达式", "len(ctx.text) > 0")], "python"),
    ("loop", "循环控制", "flow", "⟳", "判定继续回边(loop)还是退出(exit)。", ["loop", "exit"],
     [P("max_round", "最大轮数", 3), P("pass_score", "通过分数", 80)], "python"),
    ("join", "分支汇聚", "flow", "⊕", "合并多个分支的产出。", ["out"], [P("strategy", "策略(merge/concat)", "merge")], "python"),
    ("delay", "延时", "flow", "◔", "限流与退避。", ["out"], [P("seconds", "秒", 1)], "python"),
    ("subgraph", "子图调用", "flow", "⊞", "把任务委派给另一个画布项目。", ["out"], [P("project", "目标项目目录", "")], "python"),
    ("human_approval", "人工审批", "flow", "☺", "关键动作前的人工确认（无交互时按默认值）。", ["out"],
     [P("default", "默认决策(approve/reject)", "approve")], "python"),
    ("guardrail", "护栏 Guardrail", "flow", "⛨", "拦截敏感内容与越权动作。", ["out"], [P("banned", "禁用词", ["rm -rf", "DROP TABLE"])], "python"),

    # ---------------- 观察与反馈 ----------------
    ("observation", "观察 Observation", "observe", "◉", "记录本轮动作的真实结果，是 Agent 循环的反馈入口。", ["out"], [], "python"),
    ("review_observation", "观察复核 Review", "observe", "◎", "判断观察是否充分可信，决定继续/重试/重规划。", ["out"], [], "python"),
    ("format_observations", "观察格式化", "observe", "≡", "把多轮观察整理成结构化上下文。", ["out"], [P("header", "标题", "## 已有观察")], "python"),
    ("error_handler", "错误处理", "observe", "!", "捕获上游异常并给出修复方案。", ["out"], [], "python"),
    ("retry", "重试", "observe", "⟲", "带失败反馈的修正重试。", ["out"], [], "python"),
    ("fallback", "兜底", "observe", "⤓", "主路径失败时返回保底答案。", ["out"],
     [P("message", "兜底文案", "")], "python"),

    # ---------------- 多智能体协作 ----------------
    ("supervisor", "主管 Supervisor", "collab", "♔", "按组织关系把任务分派给下级 agent，并汇总它们的结果。", ["out"],
     [P("mode", "协作模式", "react", options=_MODE_OPTIONS),
      P("workers", "指定下级（agent 名称）", ["worker_a"])], "python"),
    ("worker", "工作者 Worker", "collab", "♟", "执行被分派的子任务。", ["out"],
     [P("mode", "推理模式", "react", options=_MODE_OPTIONS), P("role", "角色", "")], "python"),
    ("group_chat", "群聊 GroupChat", "collab", "◍◍", "多角色轮流发言，主持人汇总共识。", ["out"], [P("rounds", "轮数", 2)], "python"),
    ("handoff", "转交 Handoff", "collab", "⇥", "把上下文交给下游专用 agent。", ["out"],
     [P("target", "目标角色", ""), P("reason", "原因", "")], "python"),
    ("debate", "辩论 Debate", "collab", "⇄", "正反方各陈述一次，裁判裁决。", ["out"], [], "python"),
    ("message_bus", "消息总线", "collab", "⇶", "向频道广播消息并读取频道内容。", ["out"], [P("channel", "频道", "default")], "python"),

    # ---------------- 后处理与交付 ----------------
    ("formatter", "格式化输出", "post", "▧", "整理成 markdown / json / 表格。", ["out"], [P("format", "格式", "markdown")], "python"),
    ("parser", "结构化解析", "post", "▥", "从自由文本抽取结构化字段。", ["out"], [], "python"),
    ("summarizer", "摘要", "post", "▭", "按长度要求压缩内容。", ["out"], [P("max_chars", "最大字数", 300)], "python"),
    ("validator", "结构校验", "post", "⛭", "按 schema 校验结构，不通过抛错。", ["out"], [], "python"),
    ("artifact_writer", "产物写出", "post", "⤒", "把结果保存到项目 outputs/。", ["out"],
     [P("filename", "文件名", "artifact.md")], "python"),
    ("notification", "通知推送", "post", "✉", "把结果推送到 webhook。", ["out"], [P("webhook", "Webhook", "")], "python"),

    # ---------------- 框架专有 ----------------
    ("langgraph_state", "LangGraph State", "fw", "≣", "声明 LangGraph 的图状态字段。", ["out"],
     [P("fields", "字段", ["messages", "next"])], "python"),
    ("langgraph_node", "LangGraph Node", "fw", "▢", "一个 state -> state 的图节点。", ["out"],
     [P("field", "写入字段", "messages")], "python"),
    ("langgraph_edge", "LangGraph Edge", "fw", "→", "声明转移关系。", ["out"], [], "python"),
    ("autogen_assistant", "AutoGen Assistant", "fw", "▢", "AutoGen AssistantAgent。", ["out"],
     [P("agent_name", "名称", "assistant"), P("system_message", "系统消息", "")], "python"),
    ("autogen_user_proxy", "AutoGen UserProxy", "fw", "▢", "AutoGen UserProxyAgent。", ["out"],
     [P("agent_name", "名称", "user_proxy"), P("human_input_mode", "人工介入", "NEVER")], "python"),
    ("autogen_group_chat", "AutoGen GroupChat", "fw", "▢▢", "多 agent 轮询讨论。", ["out"],
     [P("agents", "成员", ["planner", "coder", "reviewer"]), P("max_round", "最大轮数", 6)], "python"),
    ("autogen_tool_agent", "AutoGen Tool Agent", "fw", "⚒", "带工具集的 AutoGen Agent。", ["out"],
     [P("mode", "推理模式", "react", options=_MODE_OPTIONS), P("max_steps", "最大步数", 6)], "python"),
    ("crewai_agent", "CrewAI Agent", "fw", "▢", "CrewAI Agent 定义。", ["out"],
     [P("role", "角色", "研究员"), P("goal", "目标", ""), P("backstory", "背景", "")], "python"),
    ("crewai_task", "CrewAI Task", "fw", "☑", "CrewAI Task 定义。", ["out"],
     [P("description", "任务描述", ""), P("expected_output", "期望输出", "")], "python"),
    ("crewai_crew", "CrewAI Crew", "fw", "▢▢", "把 agent 与 task 组装成团队。", ["out"],
     [P("process", "流程(sequential/hierarchical)", "sequential")], "python"),
    ("crewai_tool", "CrewAI Tool", "fw", "⚒", "CrewAI Tool 包装。", ["out"],
     [P("name", "名称", "search_tool"), P("description", "描述", "")], "python"),
]

NODE_TYPES: List[Dict[str, Any]] = []
for kind, label, cat, icon, desc, outputs, params, language in _DEFS:
    default_code = CODE_TEMPLATES.get(kind, '# 暂未提供默认模板\n')
    NODE_TYPES.append({
        "kind": kind,
        "label": label,
        "category": cat,
        "color": _CAT_COLOR.get(cat, "#8b5cf6"),
        "icon": icon,
        "description": desc,
        "outputs": outputs,
        "params": params,
        "language": language,
        "default_code": default_code,
    })

NODE_INDEX: Dict[str, Dict[str, Any]] = {n["kind"]: n for n in NODE_TYPES}


def get_node_type(kind: str) -> Dict[str, Any]:
    return NODE_INDEX.get(kind) or NODE_INDEX["llm"]


def list_node_types() -> Dict[str, Any]:
    return {"categories": CATEGORIES, "nodes": NODE_TYPES}


def node_meta_for_client() -> List[Dict[str, Any]]:
    """给前端的精简版（去掉 default_code，减少流量）。"""
    return [
        {k: v for k, v in n.items() if k != "default_code"}
        for n in NODE_TYPES
    ]
