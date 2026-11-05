"""节点类型注册表：工业级 Agent 编排里会出现的节点全集。

前端「右键画布新增节点」的菜单、节点面板、默认代码模板都由这里驱动。
新增节点只需要在下面加一行。
"""
from __future__ import annotations

from typing import Any, Dict, List

from .node_templates import CODE_TEMPLATES
from .node_templates_ext import EXT_TEMPLATES

ALL_TEMPLATES = {**CODE_TEMPLATES, **EXT_TEMPLATES}

# 分类：id, 名称, 颜色
CATEGORIES: List[Dict[str, str]] = [
    {"id": "io", "label": "输入输出", "color": "#22d3ee"},
    {"id": "llm", "label": "推理与决策", "color": "#8b5cf6"},
    {"id": "rag", "label": "RAG 与检索", "color": "#0ea5e9"},
    {"id": "data", "label": "数据与存储", "color": "#a16207"},
    {"id": "doc", "label": "文档与多模态", "color": "#d946ef"},
    {"id": "text", "label": "文本加工", "color": "#f97316"},
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
    ("output", "输出 Output", "io", "■", "每个智能体必须有的出口方块，返回最终答案。", ["out"],
     [P("source", "最终输出来源", "auto",
        options=[
            {"value": "auto", "label": "自动（有 agent 就用 agent 的回答）"},
            {"value": "agent", "label": "最近一次 agent 的回答"},
            {"value": "data", "label": "上游节点的输出"},
        ],
        help_text="默认 auto：链路里出现过 agent 就返回它最后一次回答，否则透传上游输出。")],
     "python"),

    # ---------------- 推理与决策 ----------------
    ("llm", "LLM 推理", "llm", "✦", "一次大模型调用，最基础的推理单元。", ["out"], [P("system", "系统提示", "")], "python"),
    ("agent", "Agent 主体", "llm", "◈", "自主 Agent，可选 ReAct / Plan / Goal 等推理模式；连到它的 tool 子图会自动注入工具。", ["out"],
     [P("mode", "推理模式", "react", options=_MODE_OPTIONS),
      P("system", "系统提示", ""), P("max_steps", "最大步数", 6)], "python"),
    ("prompt", "提示词模板", "llm", "❝", "把上游内容套进模板，做提示词工程。", ["out"], [P("requirement", "额外要求", "")], "python"),
    ("system_prompt", "系统提示词", "llm", "☰", "注入角色设定，供下游 agent/llm 复用。", ["out"], [P("persona", "角色设定", "")], "python"),
    ("planner", "任务规划", "llm", "◇", "把目标拆成有序执行计划。", ["out"], [], "python"),
    ("decomposer", "任务分解", "llm", "⋔", "输出结构化子任务列表，便于并行或分派。", ["out"], [], "python"),
    ("router", "条件路由", "llm", "⑂", "判断后走 true / false 两条出边，是分支与循环的枢纽。", ["true", "false"],
     [P("question", "判别问题", "该请求是否需要调用工具？",
        help_text="把这个判断交给模型，回答 true 走 true 出边，false 走 false 出边。"),
      P("max_loops", "循环次数上限", 0,
        help_text="0 表示不循环（默认，第一次判定继续时也会收敛）；设为 N 表示最多重跑 N 轮后强制收敛。")],
     "python"),
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

    # ---------------- RAG 与检索 ----------------
    ("intent_recognizer", "意图识别", "rag", "⌖", "把用户输入归到预定义意图，输出置信度与理由。", ["out"],
     [P("intents", "可选意图（逗号分隔）", ["咨询", "任务执行", "闲聊", "投诉", "其他"])], "python"),
    ("slot_filler", "槽位抽取", "rag", "▤", "按 schema 从输入里抽结构化字段。", ["out"],
     [P("schema", "槽位 schema（JSON）", {"who": "", "what": "", "when": "", "where": ""})], "python"),
    ("query_rewrite", "查询改写", "rag", "✎", "把口语问题改写成适合检索的查询。", ["out"], [], "python"),
    ("query_expand", "查询扩展", "rag", "⋈", "生成多条同义查询，提升召回。", ["out"],
     [P("n", "生成条数", 3)], "python"),
    ("query_router", "查询路由", "rag", "⇢", "判断问题该走哪个知识库。", ["out"],
     [P("stores", "知识库（逗号分隔）", ["docs", "faq", "manual"])], "python"),
    ("doc_loader", "文档加载", "rag", "▥", "把 pdf / docx / md / csv 抽成纯文本。", ["out"],
     [P("path", "文件路径", "docs/sample.pdf")], "python"),
    ("text_splitter", "文本切分", "rag", "⑂", "按段落和长度切块，支持重叠。", ["out"],
     [P("chunk_size", "块大小", 600), P("overlap", "重叠字符", 80)], "python"),
    ("chunk_refiner", "分块精炼", "rag", "◇", "给每个 chunk 补语义标题，便于召回与展示。", ["out"], [], "python"),
    ("vector_indexer", "向量入库", "rag", "⤓", "把文本块写进项目内向量库。", ["out"], [], "python"),
    ("hybrid_retriever", "混合检索", "rag", "⊚", "向量召回 + 关键词召回各取一份。", ["out"],
     [P("top_k", "每路条数", 4)], "python"),
    ("bm25_search", "关键词检索", "rag", "⌕", "基于词频与 IDF 的传统检索。", ["out"],
     [P("top_k", "条数", 6)], "python"),
    ("reranker", "重排 Rerank", "rag", "⇅", "让模型给候选片段打相关性分，取前 K。", ["out"],
     [P("top_k", "保留条数", 3)], "python"),
    ("context_builder", "上下文拼装", "rag", "▧", "把检索结果拼成带编号的参考上下文。", ["out"],
     [P("max_chars", "最大字符数", 3000)], "python"),
    ("citation_formatter", "引用标注", "rag", "❝", "给答案补 [1][2] 形式的来源编号。", ["out"], [], "python"),
    ("doc_grader", "相关性打分", "rag", "◐", "判断召回内容是否真的能回答问题。", ["out"], [], "python"),
    ("rag_evaluator", "RAG 质量评估", "rag", "◑", "评估答案是否被检索内容支撑。", ["out"], [], "python"),

    # ---------------- 数据与存储 ----------------
    ("db_write", "数据写入", "data", "⤒", "执行 INSERT / UPDATE / DELETE，默认禁用需显式放行。", ["out"],
     [P("sql", "写语句", ""), P("allow", "允许写入", False)], "python"),
    ("kv_store", "键值存储", "data", "▣", "KV 读写，适合存中间结果。", ["out"],
     [P("action", "动作(get/set)", "get"), P("key", "键", "default")], "python"),
    ("cache_lookup", "缓存查询", "data", "⌛", "按输入做键查缓存，命中可跳过重算。", ["out"], [], "python"),
    ("cache_write", "缓存写入", "data", "⧖", "把当前结果写进带 TTL 的缓存。", ["out"],
     [P("key", "缓存键（默认用节点名）", ""), P("ttl", "有效期（秒）", 3600)], "python"),
    ("graph_query", "图关系查询", "data", "◍", "在项目内三元组表里按关键词查关系。", ["out"],
     [P("limit", "条数", 20)], "python"),

    # ---------------- 文档与多模态 ----------------
    ("pdf_parser", "PDF 解析", "doc", "▤", "抽取 PDF 正文（需要 pypdf）。", ["out"],
     [P("path", "PDF 路径", "")], "python"),
    ("table_parser", "表格解析", "doc", "▦", "把 CSV / Markdown 表格转成结构化行。", ["out"], [], "python"),
    ("ocr_extract", "OCR 文字识别", "doc", "◫", "从图片抽文字（需要 pytesseract）。", ["out"],
     [P("path", "图片路径", "")], "python"),
    ("image_analyzer", "图像理解", "doc", "◉", "描述图片内容（需要多模态模型）。", ["out"],
     [P("path", "图片路径", "")], "python"),
    ("speech_to_text", "语音转写", "doc", "◊", "音频转文字（需要 faster-whisper）。", ["out"],
     [P("path", "音频路径", "")], "python"),

    # ---------------- 文本加工 ----------------
    ("translator", "翻译", "text", "文", "翻译成指定目标语言。", ["out"],
     [P("target", "目标语言", "English")], "python"),
    ("classifier", "分类器", "text", "⊞", "把输入归到给定标签之一。", ["out"],
     [P("labels", "标签（逗号分隔）", ["咨询", "投诉", "其他"])], "python"),
    ("extractor", "实体抽取", "text", "◎", "抽人名 / 机构 / 地点 / 金额 / 时间。", ["out"], [], "python"),
    ("sentiment", "情感分析", "text", "◔", "正向 / 中性 / 负向 + 强度。", ["out"], [], "python"),
    ("fact_checker", "事实核查", "text", "⚖", "逐条判断陈述能否被支撑。", ["out"], [], "python"),
    ("deduplicator", "去重", "text", "⊘", "按内容前缀归并重复项。", ["out"], [], "python"),
    ("merger", "多路合并", "text", "⊕", "把多路结果拼成一段。", ["out"],
     [P("separator", "分隔符", "\\n\\n")], "python"),
    ("outline_builder", "大纲生成", "text", "☰", "给主题产出多级 Markdown 大纲。", ["out"],
     [P("depth", "大纲层级", 3)], "python"),
    ("section_writer", "分段写作", "text", "▭", "按给定小标题写一节正文。", ["out"],
     [P("words", "目标字数", 400)], "python"),
    ("polisher", "润色", "text", "✧", "保持原意，改掉啰嗦与病句。", ["out"],
     [P("style", "风格", "简洁专业")], "python"),
    ("title_generator", "标题生成", "text", "❖", "给内容起若干候选标题。", ["out"],
     [P("n", "条数", 5)], "python"),

    # ---------------- 可靠性控制（归到流程控制） ----------------
    ("rate_limiter", "限流", "flow", "⏳", "控制每分钟调用次数，超了就等一下。", ["out"],
     [P("per_minute", "每分钟上限", 30)], "python"),
    ("circuit_breaker", "熔断", "flow", "⚡", "连续失败达阈值就快速失败。", ["out"],
     [P("threshold", "失败阈值", 3)], "python"),
    ("budget_guard", "预算控制", "flow", "◍", "token 用量超限就停下。", ["out"],
     [P("max_tokens", "token 上限", 50000)], "python"),
    ("cost_tracker", "成本统计", "flow", "¥", "按 token 用量估算花费。", ["out"],
     [P("price_per_k", "每千 token 价格", 0.002)], "python"),

    # ---------------- 输出处理（归到后处理） ----------------
    ("json_repair", "JSON 修复", "post", "⛭", "把模型输出里夹带的 JSON 抽出来并解析。", ["out"], [], "python"),
    ("markdown_render", "Markdown 渲染", "post", "▤", "把纯文本包装成规范 Markdown。", ["out"],
     [P("title", "标题", "")], "python"),

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

# 代码里出现这些调用，就说明这个节点在跑模型 —— 网页上应该允许给它单独配模型
LLM_CALL_MARKERS = (
    "ctx.llm", "ctx.json_prompt", "ctx.agent", "ctx.delegate",
    "ctx.describe_image", "ctx.transcribe", "ctx.rerank",
)

# 更细的正则版：用于扫描用户自己改过的节点代码
import re as _re

_LLM_PATTERNS = [
    _re.compile(r"\bctx\.llm(_stream)?\s*\("),
    _re.compile(r"\bctx\.json_prompt\s*\("),
    _re.compile(r"\bctx\.agent\s*\("),
    _re.compile(r"\bctx\.delegate\s*\("),
    _re.compile(r"\bctx\.describe_image\s*\("),
    _re.compile(r"\bctx\.transcribe\s*\("),
    _re.compile(r"\bctx\.rerank\s*\("),
    # 原生块写法
    _re.compile(r"\bChatOpenAI\s*\("),
    _re.compile(r"\bcreate_agent\s*\("),
    _re.compile(r"\bcreate_react_agent\s*\("),
    _re.compile(r"\bAgentExecutor\s*\("),
    _re.compile(r"\bllm\.(invoke|bind|stream|batch)\s*\("),
    _re.compile(r"\bmodel\.(invoke|bind|stream)\s*\("),
]


def detect_llm_usage(code: str, kind: str = "") -> bool:
    """扫描一段节点源码，判断它会不会调用大模型。

    保存时会用它重新判定每个节点，用户手改了代码（加了或去掉了模型调用）
    之后，右键里的「配置模型」入口会跟着变。
    """
    if kind in ("llm", "agent", "supervisor", "worker", "group_chat", "debate"):
        return True
    text = code or ""
    if not text:
        return False
    if any(m in text for m in LLM_CALL_MARKERS):
        return True
    return any(p.search(text) for p in _LLM_PATTERNS)


def _uses_llm(kind: str, code: str) -> bool:
    return detect_llm_usage(code, kind)


for kind, label, cat, icon, desc, outputs, params, language in _DEFS:
    default_code = ALL_TEMPLATES.get(kind, '# 暂未提供默认模板\n')
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
        "uses_llm": _uses_llm(kind, default_code),
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
