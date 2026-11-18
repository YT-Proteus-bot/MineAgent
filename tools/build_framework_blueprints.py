"""把主流 Agent 编排框架的架构还原成 MineAgent 画布。

每个条目对应一张画布，节点组合体现该框架的核心拓扑。
只用于架构对比与学习，不代表这些产品的全部能力。
"""
from __future__ import annotations

import json
import urllib.request

BASE = "http://127.0.0.1:8000"
GAP = 380


def N(kind, label, params=None, role="main", org=None):
    return {"kind": kind, "label": label, "params": params or {}, "role": role, "org": org}


# links: (from_idx, to_idx, handle)
BLUEPRINTS = [
    # ------------------------------------------------------------------ 开源框架
    {
        "name": "开源 · LangGraph 状态图",
        "framework": "langchain",
        "note": "StateGraph：节点 + 条件边 + 检查点。显式控制流，最接近「图」的编排。",
        "nodes": [
            N("input", "输入", role="input"),
            N("planner", "规划", role="main"),
            N("agent", "Agent（ReAct）", {"mode": "react", "max_steps": 6}),
            N("router", "条件边：继续还是收尾？", {"question": "是否已经可以给出最终答案？"}),
            N("tool", "工具", role="aux"),
            N("output", "输出", role="output"),
        ],
        "links": [[0, 1], [1, 2], [2, 3], [3, 4, "true"], [4, 2], [3, 5, "false"]],
    },
    {
        "name": "开源 · CrewAI 角色流水线",
        "framework": "crewai",
        "note": "Crew = Agent + Task 的集合，默认顺序执行；靠 role / goal / backstory 分工。",
        "nodes": [
            N("input", "输入", role="input"),
            N("planner", "任务拆解", role="main"),
            N("agent", "研究员（Researcher）", {"mode": "simple", "system_prompt": "你负责收集资料、核实事实。"}),
            N("agent", "写手（Writer）", {"mode": "simple", "system_prompt": "你负责把资料写成结构清晰的成稿。"}),
            N("critic", "审校（Reviewer）", role="aux"),
            N("output", "输出", role="output"),
        ],
        "links": [[0, 1], [1, 2], [2, 3], [3, 4], [4, 5]],
    },
    {
        "name": "开源 · CrewAI 层级模式",
        "framework": "crewai",
        "note": "hierarchical 流程：Manager 分派任务给 Crew 成员并验收，比顺序模式灵活。",
        "nodes": [
            N("input", "输入", role="input"),
            N("supervisor", "Manager", {"max_workers": 4}),
            N("worker", "成员 A", {"role": "调研"}),
            N("worker", "成员 B", {"role": "撰写"}),
            N("critic", "验收", role="aux"),
            N("output", "输出", role="output"),
        ],
        "links": [[0, 1], [1, 2], [1, 3], [2, 4], [3, 4], [4, 5]],
    },
    {
        "name": "开源 · AutoGen 对话驱动",
        "framework": "autogen",
        "note": "多 Agent 用对话推进：Assistant 干活，UserProxy 扮演用户逼问，GroupChat 管发言人顺序。",
        "nodes": [
            N("input", "输入", role="input"),
            N("group_chat", "GroupChat 主持人", {"rounds": 3}),
            N("agent", "AssistantAgent", {"mode": "simple"}),
            N("agent", "UserProxyAgent", {"mode": "simple", "system_prompt": "你是代理用户，负责提需求、挑毛病。"}),
            N("formatter", "收敛结论", role="aux"),
            N("output", "输出", role="output"),
        ],
        "links": [[0, 2], [2, 1], [1, 3], [3, 2], [1, 4], [4, 5]],
    },
    {
        "name": "开源 · MetaGPT 软件公司",
        "framework": "metagpt",
        "note": "把软件公司的 SOP 搬进多 Agent：产品经理 → 架构师 → 工程师 → QA，按角色顺序产出。",
        "nodes": [
            N("input", "需求", role="input"),
            N("agent", "产品经理（PRD）", {"mode": "simple", "system_prompt": "输出 PRD 与验收标准。"}),
            N("agent", "架构师（设计）", {"mode": "simple", "system_prompt": "输出技术方案与模块划分。"}),
            N("agent", "工程师（实现）", {"mode": "simple", "system_prompt": "按方案写实现代码。"}),
            N("critic", "QA 验收", role="aux"),
            N("output", "交付", role="output"),
        ],
        "links": [[0, 1], [1, 2], [2, 3], [3, 4], [4, 5]],
    },
    {
        "name": "开源 · Dify Chatflow",
        "framework": "dify",
        "note": "面向多轮对话的节点式编排：会话变量 + 意图分支 + 知识库，非技术人员也能搭。",
        "nodes": [
            N("input", "用户消息", role="input"),
            N("memory", "会话变量", role="aux"),
            N("intent_recognizer", "意图识别", {"intents": ["知识问答「, 」闲聊「, 」转人工"]}),
            N("rag_retriever", "知识库检索", {"top_k": 4}),
            N("llm", "回答", {"system": "结合会话历史与检索结果作答。"}),
            N("output", "回复", role="output"),
        ],
        "links": [[0, 1], [1, 2], [2, 3], [3, 4], [4, 5]],
    },
    {
        "name": "开源 · n8n 自动化流水线",
        "framework": "custom",
        "note": "本质是工作流自动化，2023 起集成 LangChain 节点；强项在把 AI 接到几百种现有业务系统。",
        "nodes": [
            N("input", "触发器（Webhook）", role="input"),
            N("http_request", "拉取业务数据", role="main"),
            N("llm", "AI 处理", {"system": "把原始数据整理成摘要。"}),
            N("condition", "是否达到报警阈值", {"expression": "score > 0.8"}),
            N("tool", "推送通知", role="aux"),
            N("output", "记录结果", role="output"),
        ],
        "links": [[0, 1], [1, 2], [2, 3], [3, 4, "true"], [4, 5], [3, 5, "false"]],
    },
    {
        "name": "开源 · Flowise 可视化 RAG",
        "framework": "custom",
        "note": "节点式拖拽 + Agent 模板，偏 RAG 与工具链组装；状态用分布式存储同步。",
        "nodes": [
            N("input", "文档 / 提问", role="input"),
            N("doc_loader", "文档加载", role="main"),
            N("text_splitter", "文本切分", {"chunk_size": 600, "overlap": 80}),
            N("vector_indexer", "向量入库", role="aux"),
            N("hybrid_retriever", "混合检索", {"top_k": 4}),
            N("llm", "生成回答", {"system": "只根据检索到的内容回答。"}),
            N("output", "输出", role="output"),
        ],
        "links": [[0, 1], [1, 2], [2, 3], [3, 4], [4, 5], [5, 6]],
    },
    {
        "name": "开源 · Langflow 线性链",
        "framework": "custom",
        "note": "把 LangChain 的组件（Prompt / LLM / Tool）图形化拼装，适合快速试提示词。",
        "nodes": [
            N("input", "输入", role="input"),
            N("system_prompt", "系统提示词", {"persona": "你是一名严谨的分析师。"}),
            N("llm", "LLM", {}),
            N("formatter", "输出整理", role="aux"),
            N("output", "输出", role="output"),
        ],
        "links": [[0, 1], [1, 2], [2, 3], [3, 4]],
    },
    {
        "name": "开源 · SmolAgents 代码行动",
        "framework": "smolagents",
        "note": "HuggingFace 出品，主张「用写代码代替调工具」，CodeAgent 直接把行动写成 Python 片段。",
        "nodes": [
            N("input", "任务", role="input"),
            N("agent", "CodeAgent", {"mode": "react", "system_prompt": "用 Python 代码表达每一步行动。"}),
            N("code_interpreter", "代码执行沙箱", role="aux"),
            N("observation", "观察执行结果", role="aux"),
            N("output", "输出", role="output"),
        ],
        "links": [[0, 1], [1, 2], [2, 3], [3, 1], [1, 4]],
    },

    # ------------------------------------------------------------------ 闭源平台
    {
        "name": "闭源 · OpenAI Agent Builder",
        "framework": "openai_agents",
        "note": "可视化画布：Start / Agent / File search / Guardrails / MCP。官方已宣布 2026-11-30 关停。",
        "nodes": [
            N("input", "Start", role="input"),
            N("agent", "分流 Agent", {"mode": "simple", "system_prompt": "判断这次请求属于哪一类。"}),
            N("self_check", "Guardrails 护栏", role="aux"),
            N("rag_retriever", "File search（向量库）", {"top_k": 4}),
            N("agent", "回答 Agent", {"mode": "simple"}),
            N("output", "输出", role="output"),
        ],
        "links": [[0, 1], [1, 2], [2, 3], [3, 4], [4, 5]],
    },
    {
        "name": "闭源 · AWS Bedrock Agents",
        "framework": "custom",
        "note": "Agent + Action Groups（调 API）+ Knowledge Base（检索）+ Guardrails，全托管、走 IAM 权限。",
        "nodes": [
            N("input", "用户请求", role="input"),
            N("agent", "Bedrock Agent", {"mode": "react", "max_steps": 8}),
            N("tool", "Action Group（Lambda）", role="aux"),
            N("rag_retriever", "Knowledge Base", {"top_k": 5}),
            N("self_check", "Guardrails", role="aux"),
            N("output", "响应", role="output"),
        ],
        "links": [[0, 1], [1, 2], [1, 3], [2, 4], [3, 4], [4, 5]],
    },
    {
        "name": "闭源 · 字节 Coze Bot",
        "framework": "custom",
        "note": "Bot = 人设 + 插件 + 工作流 + 知识库；面向非开发者，5 分钟能出 Demo。",
        "nodes": [
            N("input", "用户消息", role="input"),
            N("intent_recognizer", "意图分流", {"intents": ["闲聊「, 」查资料「, 」执行操作"]}),
            N("router", "需要调插件吗？", {"question": "是否需要调用外部插件？"}),
            N("tool", "插件 / 工作流", role="aux"),
            N("llm", "Bot 回复", {"system": "按人设口吻回答。"}),
            N("output", "输出", role="output"),
        ],
        "links": [[0, 1], [1, 2], [2, 3, "true"], [2, 4, "false"], [3, 4], [4, 5]],
    },
    {
        "name": "闭源 · DeepSeek Super-agent",
        "framework": "langchain",
        "note": "Router 持续接单并分派，Worker 各自独立上下文并行执行；强调常驻、主动、可恢复。",
        "nodes": [
            N("input", "多渠道消息（IM / GitHub / 邮件）", role="input"),
            N("supervisor", "Router（常驻协调）", {"max_workers": 4}),
            N("worker", "Worker：问题复现", {"role": "复现与定位"}),
            N("worker", "Worker：代码审查", {"role": "审查与修复"}),
            N("merge", "汇总与汇报", role="aux"),
            N("output", "输出", role="output"),
        ],
        "links": [[0, 1], [1, 2], [1, 3], [2, 4], [3, 4], [4, 5]],
    },
]


def post(path, body=None):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method="POST",
                                 headers={"Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read().decode("utf-8"))


def build_graph(bp):
    specs = bp["nodes"]
    names = [f"{n['kind']}_{i}" for i, n in enumerate(specs, 1)]
    nodes = []
    for i, spec in enumerate(specs, 1):
        nodes.append({
            "id": f"n{i}",
            "type": "agent",
            "position": {"x": (i - 1) * GAP, "y": 0},
            "data": {
                "kind": spec["kind"],
                "label": spec["label"],
                "name": names[i - 1],
                "description": "",
                "code": "",
                "language": "python",
                "params": spec.get("params") or {},
                "org": spec.get("org") or {},
                "role": spec.get("role", "main"),
            },
        })
    edges = []
    for idx, (s, t, *rest) in enumerate(bp["links"]):
        handle = rest[0] if rest else "out"
        edges.append({
            "id": f"e{s}_{t}_{idx}",
            "source": f"n{s + 1}",
            "target": f"n{t + 1}",
            "sourceHandle": handle,
            "targetHandle": "in",
            "type": "agent",
            "label": handle if handle != "out" else None,
            "data": {"branch": handle if handle != "out" else None},
        })
    return {"nodes": nodes, "edges": edges, "viewport": {"x": 0, "y": 0, "zoom": 0.62},
            "background": {}}


def main():
    created = []
    for bp in BLUEPRINTS:
        try:
            canvas = post("/api/canvases", {"name": bp["name"], "framework": bp["framework"]})
        except Exception as exc:  # noqa: BLE001
            print(f"✘ 创建失败 {bp['name']}: {exc}")
            continue
        graph = build_graph(bp)
        try:
            res = post(f"/api/canvases/{canvas['id']}/save", graph)
            counts = res["constraints"]["counts"]
            created.append({
                "id": canvas["id"], "name": bp["name"], "framework": bp["framework"],
                "nodes": len(graph["nodes"]), "edges": len(graph["edges"]),
                "violations": counts, "note": bp["note"],
            })
            print(f"✔ {bp['name']:32s} {len(graph['nodes'])} 节点 约束={counts}")
        except Exception as exc:  # noqa: BLE001
            print(f"✘ 保存失败 {bp['name']}: {exc}")
    print(f"\n共创建 {len(created)} 张画布")
    print(json.dumps(created, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
