"""开源智能体的「架构指纹」库。

一个项目一条记录，包含三样东西：
- behaviors：行为指纹 —— 这个项目区别于别家的关键行为，每条都能被验证
- nodes / edges：等价的画布拓扑
- codes：需要特殊逻辑的节点代码（让行为真的对上，而不是只有形状）

用途：
- 助手按项目名查指纹，据此生成画布（比现场推理准得多）
- 测试脚本按 behaviors 做回归，验「行为是否对齐」而不是「长得像不像」

新增一个项目 = 加一条记录。节点 kind 必须是 node_registry 里真实存在的。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def _node(key: str, kind: str, label: str, params: Optional[Dict[str, Any]] = None,
          code: str = "") -> Dict[str, Any]:
    item: Dict[str, Any] = {"key": key, "kind": kind, "label": label,
                            "params": params or {}}
    if code:
        item["code"] = code
    return item


def _edge(source: str, target: str, branch: str = "") -> Dict[str, str]:
    item = {"source": source, "target": target}
    if branch:
        item["branch"] = branch
    return item


ARCHITECTURES: List[Dict[str, Any]] = [
    # ------------------------------------------------------------------ #
    # AutoGPT：目标 → 任务队列 → 逐任务执行 → 反思 → 重规划
    # ------------------------------------------------------------------ #
    {
        "id": "autogpt",
        "name": "AutoGPT",
        "framework": "langchain",
        "paradigm": "goal-driven task queue loop",
        "summary": "把目标拆成任务队列，逐个执行并反思，没完成就重新规划，直到收敛。",
        "behaviors": [
            "目标先被拆成有序任务列表，而不是直接回答",
            "每轮只取队首任务执行，不做并行",
            "执行结果经过一次自我反思/批评才写回",
            "结果写回后由路由判断「是否已达成目标」，未达成则继续取任务",
            "同一任务的执行次数有上限，防止原地打转",
        ],
        "nodes": [
            _node("goal", "input", "目标"),
            _node("plan", "planner", "任务拆解", {"max_steps": 8}),
            _node("queue", "memory", "任务队列"),
            _node("pick", "kv_store", "取队首任务", {"action": "get", "key": "current_task"}),
            _node("exec", "agent", "执行任务", {"mode": "react", "max_steps": 6}),
            _node("critique", "critic", "自我批评"),
            _node("remember", "memory", "结果写回记忆"),
            _node("check", "router", "目标是否达成？", {
                "question": "基于已有结果判断：原始目标是否已经完成？完成回答 true，否则 false。",
                "max_loops": 6,
            }),
            _node("out", "output", "最终结果"),
        ],
        "edges": [
            _edge("goal", "plan"),
            _edge("plan", "queue"),
            _edge("queue", "pick"),
            _edge("pick", "exec"),
            _edge("exec", "critique"),
            _edge("critique", "remember"),
            _edge("remember", "check"),
            _edge("check", "out", "true"),
            _edge("check", "pick", "false"),
        ],
        "codes": {
            "pick": (
                "def run(ctx):\n"
                "    \"\"\"从任务队列里取队首任务；队列空了就用目标兜底。\"\"\"\n"
                "    tasks = ctx.state.get('tasks') or []\n"
                "    if isinstance(tasks, str):\n"
                "        tasks = [t.strip() for t in tasks.splitlines() if t.strip()]\n"
                "    current = tasks[0] if tasks else ctx.text\n"
                "    ctx.state['tasks'] = tasks[1:]\n"
                "    ctx.state['current_task'] = current\n"
                "    ctx.emit('task', {'remaining': len(ctx.state['tasks']), 'current': current[:80]})\n"
                "    return {'data': current}\n"
            ),
        },
        "notes": "关键在 pick 节点：真正的 AutoGPT 靠任务队列推进，不是靠循环重问同一个问题。",
    },

    # ------------------------------------------------------------------ #
    # MetaGPT：SOP 流水线，上游产物即下游输入
    # ------------------------------------------------------------------ #
    {
        "id": "metagpt",
        "name": "MetaGPT",
        "framework": "metagpt",
        "paradigm": "SOP assembly line",
        "summary": "把软件开发拆成产品 → 架构 → 开发 → 测试的流水线，每个角色只做自己那一段。",
        "behaviors": [
            "角色按固定 SOP 顺序串行，不做自由对话",
            "每个角色产出结构化文档，作为下一角色的输入",
            "流水线有明确终点（测试通过或产出交付物），不回头重跑",
            "失败只在当前环节重试，不回退到上游",
        ],
        "nodes": [
            _node("req", "input", "需求"),
            _node("pm", "agent", "产品经理", {"mode": "plan_execute", "max_steps": 4}),
            _node("prd", "formatter", "PRD 文档"),
            _node("arch", "agent", "架构师", {"mode": "plan_execute", "max_steps": 4}),
            _node("design", "formatter", "系统设计"),
            _node("dev", "agent", "工程师", {"mode": "react", "max_steps": 8}),
            _node("code", "formatter", "代码实现"),
            _node("qa", "agent", "测试", {"mode": "react", "max_steps": 5}),
            _node("gate", "router", "测试是否通过？", {
                "question": "根据测试结论判断：是否通过？通过回答 true，否则 false。",
                "max_loops": 3,
            }),
            _node("deliver", "output", "交付"),
        ],
        "edges": [
            _edge("req", "pm"), _edge("pm", "prd"),
            _edge("prd", "arch"), _edge("arch", "design"),
            _edge("design", "dev"), _edge("dev", "code"),
            _edge("code", "qa"), _edge("qa", "gate"),
            _edge("gate", "deliver", "true"),
            _edge("gate", "dev", "false"),
        ],
        "codes": {},
        "notes": "SOP 的要点是「产物驱动」：每个角色吃上一环的产物，而不是共享对话历史。",
    },

    # ------------------------------------------------------------------ #
    # CrewAI：角色 + 任务 + 顺序/层级协作
    # ------------------------------------------------------------------ #
    {
        "id": "crewai",
        "name": "CrewAI",
        "framework": "crewai",
        "paradigm": "role-based crew",
        "summary": "每个角色有 role/goal/backstory，任务按顺序分配给角色，最后汇总。",
        "behaviors": [
            "每个 agent 有独立角色设定（role/goal/backstory），互不共享上下文",
            "任务与角色一一绑定，不是自由发言",
            "按顺序推进，前一任务的产出成为后一任务的输入",
            "最后一个汇总任务把各角色成果合并",
        ],
        "nodes": [
            _node("topic", "input", "目标"),
            _node("researcher", "agent", "研究员", {"mode": "react", "max_steps": 6}),
            _node("analyst", "agent", "分析师", {"mode": "react", "max_steps": 6}),
            _node("writer", "agent", "撰写人", {"mode": "tool_call", "max_steps": 4}),
            _node("merge", "merger", "汇总"),
            _node("out", "output", "成果"),
        ],
        "edges": [
            _edge("topic", "researcher"),
            _edge("researcher", "analyst"),
            _edge("analyst", "writer"),
            _edge("writer", "merge"),
            _edge("merge", "out"),
        ],
        "codes": {
            "researcher": (
                "def run(ctx):\n"
                "    \"\"\"研究员：只负责收集事实，不下结论。\"\"\"\n"
                "    system = ('你是研究员。只收集与目标相关的事实、数据与来源，'\n"
                "              '不下判断、不写建议。用要点列出。')\n"
                "    facts = ctx.llm(ctx.text, system=system)\n"
                "    ctx.state['facts'] = facts\n"
                "    return {'data': facts}\n"
            ),
            "analyst": (
                "def run(ctx):\n"
                "    \"\"\"分析师：基于研究员给出的事实做判断，不重新收集。\"\"\"\n"
                "    facts = ctx.state.get('facts') or ctx.text\n"
                "    system = '你是分析师。只能基于给定事实分析，不得引入新事实。'\n"
                "    analysis = ctx.llm(f'事实：\\n{facts}\\n\\n请分析。', system=system)\n"
                "    ctx.state['analysis'] = analysis\n"
                "    return {'data': analysis}\n"
            ),
        },
        "notes": "CrewAI 的隔离性体现在「每个角色只拿自己的输入」，不是共享整段对话。",
    },

    # ------------------------------------------------------------------ #
    # DeepSeek Harness：插件化 agent runtime
    # 依据本地 checkout（@deepseek-ai/dsh-*，338 个包）的实际分层提炼
    # ------------------------------------------------------------------ #
    {
        "id": "deepseek-harness",
        "name": "DeepSeek Harness",
        "framework": "harness",
        "paradigm": "plugin-composed agent runtime",
        "summary": "一切皆插件（Cordis IoC）：agent 循环、工具、压缩策略、审批、沙箱都可替换；"
                   "上下文按预算分层压缩，会话持久化可恢复，子代理独立上下文。",
        "behaviors": [
            "系统提示词是装配出来的：基础人格 + 项目指令(AGENTS.md) + 技能清单 + 环境事实，"
            "不是一句写死的 prompt",
            "工具调用过闸门：危险操作走人工审批，文件/命令走沙箱策略",
            "工具执行器可替换：native 直调，或 PTC（把工具当代码写）",
            "上下文按 token 预算分层压缩（摘要 + 大输出卸载 + 工具结果裁剪），不是简单截断",
            "会话持久化并可重建（projection），中断后能接着跑",
            "子代理有独立上下文，可 fork（继承对话）或 spawn（全新）",
        ],
        "nodes": [
            _node("input", "input", "用户输入"),
            _node("skills", "skill", "技能清单"),
            _node("prompt", "system_prompt", "系统提示词装配", {
                "template": "你是 {{persona}}。\n\n{{instructions}}\n\n"
                            "可用技能：{{skills}}\n\n当前环境：{{env}}",
            }),
            _node("loop", "agent", "Agent 循环", {"mode": "react", "max_steps": 12}),
            _node("gate", "router", "要调工具吗？", {
                "question": "根据当前对话判断：这一步是否需要调用工具？"
                            "需要回答 true，可以直接作答回答 false。",
                "max_loops": 12,
            }),
            _node("approval", "human_approval", "审批闸门", {
                "policy": "危险操作（写文件 / 执行命令 / 发请求）需要人工确认",
            }),
            _node("sandbox", "guardrail", "沙箱与权限", {
                "rule": "命令在沙箱内执行；越权访问直接拒绝并回传原因",
            }),
            _node("toolkit", "tool", "工具执行"),
            _node("observe", "observation", "观察结果"),
            _node("compact", "summarizer", "上下文压缩", {"max_chars": 6000}),
            _node("persist", "memory", "会话持久化"),
            _node("out", "output", "最终回答"),
        ],
        "edges": [
            _edge("input", "skills"),
            _edge("skills", "prompt"),
            _edge("prompt", "loop"),
            _edge("loop", "gate"),
            _edge("gate", "approval", "true"),
            _edge("approval", "sandbox"),
            _edge("sandbox", "toolkit"),
            _edge("toolkit", "observe"),
            _edge("observe", "compact"),
            _edge("compact", "loop"),
            _edge("gate", "persist", "false"),
            _edge("persist", "out"),
        ],
        "codes": {
            "compact": (
                "def run(ctx):\n"
                "    \"\"\"按预算压缩，而不是无脑截断：保住最近几轮 + 早期要点。\"\"\"\n"
                "    budget = int(ctx.params.get('max_chars') or 6000)\n"
                "    history = ctx.state.setdefault('transcript', [])\n"
                "    history.append(str(ctx.text))\n"
                "    joined = '\\n'.join(history)\n"
                "    if len(joined) <= budget:\n"
                "        return {'data': ctx.text}\n"
                "    # 超预算：前半段摘要、后半段原文\n"
                "    head, tail = joined[: len(joined) - budget // 2], joined[-budget // 2:]\n"
                "    digest = ctx.llm(f'把下面这段历史压缩成要点（保留结论、待办、关键事实）：\\n{head}')\n"
                "    ctx.state['transcript'] = [digest, tail]\n"
                "    ctx.emit('compacted', {'before': len(joined), 'after': len(digest) + len(tail)})\n"
                "    return {'data': f'【早期摘要】\\n{digest}\\n\\n【最近】\\n{tail}'}\n"
            ),
            "persist": (
                "def run(ctx):\n"
                "    \"\"\"会话落盘：中断后能按同一份状态接着跑。\"\"\"\n"
                "    transcript = ctx.state.get('transcript') or []\n"
                "    ctx.write_file('session.jsonl',\n"
                "                   '\\n'.join(str(x)[:2000] for x in transcript))\n"
                "    return {'data': ctx.text}\n"
            ),
        },
        "notes": "插件系统本身（Cordis 容器、插件市场、客户端插件）不在画布表达范围内——"
                 "它能替换上面每一层，画布只能还原被组装出来的那套运行时结构。"
                 "PTC 执行器用 code_interpreter 表达会更贴切，但会让主链路变复杂，这里用 tool 统一。",
    },

    # ------------------------------------------------------------------ #
    # BabyAGI：任务队列 + 优先级重排序
    # ------------------------------------------------------------------ #
    {
        "id": "babyagi",
        "name": "BabyAGI",
        "framework": "langchain",
        "paradigm": "task queue with reprioritization",
        "summary": "三个角色分工：执行任务、按目标生成新任务、按优先级重排整个队列。"
                   "和 AutoGPT 的区别就在这里——它会反复重排，而不是只取队首。",
        "behaviors": [
            "任务列表每一轮都被重新按优先级排序，不是固定顺序",
            "执行结果存进记忆（可按相似度检索），供后续任务参考",
            "每执行完一个任务就根据结果生成新任务并追加到列表",
            "队列为空时才结束，否则一直循环",
            "有循环上限，防止任务无限增殖",
        ],
        "nodes": [
            _node("objective", "input", "目标"),
            _node("plan", "planner", "初始任务列表", {"max_steps": 6}),
            _node("merge", "merger", "任务池"),
            _node("priority", "agent", "优先级排序", {"mode": "cot", "max_steps": 2}),
            _node("gate", "router", "队列空了吗？", {
                "question": "任务列表是否已经为空？为空回答 true，否则 false。",
                "max_loops": 10,
            }),
            _node("pick", "kv_store", "取最高优先级任务", {"action": "pop"}),
            _node("exec", "agent", "执行任务", {"mode": "react", "max_steps": 6}),
            _node("store", "memory", "结果存记忆"),
            _node("creator", "llm", "生成新任务"),
            _node("out", "output", "最终结果"),
        ],
        "edges": [
            _edge("objective", "plan"),
            _edge("plan", "merge"),
            _edge("merge", "priority"),
            _edge("priority", "gate"),
            _edge("gate", "out", "true"),
            _edge("gate", "pick", "false"),
            _edge("pick", "exec"),
            _edge("exec", "store"),
            _edge("store", "creator"),
            _edge("creator", "merge"),
        ],
        "codes": {
            "priority": (
                "def run(ctx):\n"
                "    \"\"\"把任务池按对目标的重要度重排——BabyAGI 的核心动作。\"\"\"\n"
                "    pool = ctx.state.get('task_pool') or ctx.parse_json(ctx.text) or []\n"
                "    if isinstance(pool, str):\n"
                "        pool = [t for t in pool.splitlines() if t.strip()]\n"
                "    if len(pool) > 1:\n"
                "        ranked = ctx.llm(\n"
                "            '目标是：' + str(ctx.state.get('objective', '')) +\n"
                "            '\\n任务列表：\\n' + '\\n'.join(f'- {t}' for t in pool) +\n"
                "            '\\n按对目标的重要度从高到低重排，只输出 JSON 数组。')\n"
                "        ctx.state['task_pool'] = ctx.parse_json(ranked) or pool\n"
                "    ctx.emit('prioritized', {'count': len(ctx.state['task_pool'])})\n"
                "    return {'data': ctx.state['task_pool']}\n"
            ),
            "pick": (
                "def run(ctx):\n"
                "    \"\"\"取排在最前面的那个任务。\"\"\"\n"
                "    pool = ctx.state.get('task_pool') or []\n"
                "    current = pool[0] if pool else ''\n"
                "    ctx.state['task_pool'] = pool[1:]\n"
                "    ctx.state['current_task'] = current\n"
                "    return {'data': str(current)}\n"
            ),
            "creator": (
                "def run(ctx):\n"
                "    \"\"\"根据执行结果和剩余任务，生成新任务并追加回池子。\"\"\"\n"
                "    pool = ctx.state.get('task_pool') or []\n"
                "    fresh = ctx.llm(\n"
                "        '目标：' + str(ctx.state.get('objective', '')) +\n"
                "        '\\n刚完成的任务：' + str(ctx.state.get('current_task', '')) +\n"
                "        '\\n结果：' + str(ctx.text)[:1500] +\n"
                "        '\\n剩余任务：' + '\\n'.join(f'- {t}' for t in pool) +\n"
                "        '\\n请只输出需要新增的任务，每行一个；没有就输出空。')\n"
                "    added = [t.strip(' -') for t in str(fresh).splitlines() if t.strip(' -')]\n"
                "    ctx.state['task_pool'] = pool + added\n"
                "    ctx.emit('task_added', {'added': len(added), 'total': len(ctx.state['task_pool'])})\n"
                "    return {'data': ctx.text}\n"
            ),
        },
        "notes": "BabyAGI 与 AutoGPT 的差别就在 priority 节点：它每轮重排整个队列，"
                 "而不是按固定顺序执行。少了这一步就变成 AutoGPT 了。",
    },

    # ------------------------------------------------------------------ #
    # CAMEL：双向角色扮演对话
    # ------------------------------------------------------------------ #
    {
        "id": "camel",
        "name": "CAMEL",
        "framework": "langchain",
        "paradigm": "role-playing dialogue",
        "summary": "两个 agent 分别扮演『任务提出者』和『任务执行者』，交替发言，"
                   "靠 inception prompt 维持角色，直到出现终止信号。",
        "behaviors": [
            "两个 agent 的角色由 inception prompt 在开跑前一次性设定",
            "双方交替发言，每一方都能看到对方的全部历史",
            "由『提出者』判断是否已达成目标，达成后输出终止标记",
            "有轮次上限，防止双方互相客套停不下来",
        ],
        "nodes": [
            _node("task", "input", "任务"),
            _node("setup", "system_prompt", "角色设定", {
                "template": "你是一场协作对话中的一方。\n"
                            "AI User 负责把任务拆成具体要求；AI Assistant 负责给出可执行方案。\n"
                            "任务：{{task}}",
            }),
            _node("merge", "merger", "对话上下文"),
            _node("user", "agent", "AI User（提出者）", {"mode": "cot", "max_steps": 2}),
            _node("assistant", "agent", "AI Assistant（执行者）", {"mode": "cot", "max_steps": 2}),
            _node("gate", "router", "是否收工？", {
                "question": "对话中是否已出现 <CAMEL_TASK_DONE> 或任务已明确完成？"
                            "完成回答 true，否则 false。",
                "max_loops": 8,
            }),
            _node("out", "output", "对话结论"),
        ],
        "edges": [
            _edge("task", "setup"),
            _edge("setup", "merge"),
            _edge("merge", "user"),
            _edge("user", "assistant"),
            _edge("assistant", "gate"),
            _edge("gate", "out", "true"),
            _edge("gate", "merge", "false"),
        ],
        "codes": {
            "user": (
                "def run(ctx):\n"
                "    \"\"\"提出者：根据执行者上一轮的回复提出下一个具体要求。\"\"\"\n"
                "    reply = ctx.llm(\n"
                "        '你是 AI User（任务提出者）。'\n"
                "        '根据 AI Assistant 的最新回复，提出下一步具体要求。'\n"
                "        '如果任务已经完成，只输出 <CAMEL_TASK_DONE>。\\n\\n'\n"
                "        f'Assistant 最新回复：\\n{ctx.text}')\n"
                "    ctx.state['last_user'] = reply\n"
                "    return {'data': reply}\n"
            ),
            "assistant": (
                "def run(ctx):\n"
                "    \"\"\"执行者：正面回应提出者的要求，给出可执行内容。\"\"\"\n"
                "    reply = ctx.llm(\n"
                "        '你是 AI Assistant（任务执行者）。'\n"
                "        '针对 AI User 的要求给出具体、可执行的答复，不要反问。\\n\\n'\n"
                "        f'AI User：\\n{ctx.text}')\n"
                "    return {'data': reply}\n"
            ),
        },
        "notes": "CAMEL 的本质是『没有外部裁判』——双方自己判断是否结束，"
                 "所以 gate 必须读对话内容而不是读状态位。",
    },

    # ------------------------------------------------------------------ #
    # Voyager：技能库 + 自动课程
    # ------------------------------------------------------------------ #
    {
        "id": "voyager",
        "name": "Voyager",
        "framework": "langchain",
        "paradigm": "skill library + automatic curriculum",
        "summary": "自动生成由易到难的课程，写代码执行，成功就存成可复用技能，"
                   "失败就带着报错重写。",
        "behaviors": [
            "下一步做什么由『自动课程』决定，难度递进，不是一次列全",
            "写代码前先检索技能库，优先复用已有技能",
            "执行失败时把报错和输出带回重写，有重试上限",
            "成功执行后把代码存进技能库，供后续按描述检索",
        ],
        "nodes": [
            _node("goal", "input", "目标/环境"),
            _node("curriculum", "planner", "自动课程", {"max_steps": 5}),
            _node("next_gate", "router", "还有下一课吗？", {
                "question": "自动课程是否还有下一个任务？有回答 true，全部完成回答 false。",
                "max_loops": 8,
            }),
            _node("skill_lib", "memory", "技能库"),
            _node("recall", "rag_retriever", "检索已有技能"),
            _node("coder", "agent", "写代码", {"mode": "react", "max_steps": 6}),
            _node("run_code", "code_interpreter", "执行代码"),
            _node("check", "self_check", "是否达成"),
            _node("gate", "router", "成功了吗？", {
                "question": "代码执行是否成功、且达成了当前课程目标？成功回答 true，否则 false。",
                "max_loops": 5,
            }),
            _node("learn", "memory", "技能入库"),
            _node("out", "output", "最终能力"),
        ],
        "edges": [
            _edge("goal", "curriculum"),
            _edge("goal", "skill_lib"),
            _edge("curriculum", "next_gate"),
            _edge("next_gate", "recall", "true"),
            _edge("next_gate", "out", "false"),
            _edge("skill_lib", "recall"),
            _edge("recall", "coder"),
            _edge("coder", "run_code"),
            _edge("run_code", "check"),
            _edge("check", "gate"),
            _edge("gate", "learn", "true"),
            _edge("gate", "coder", "false"),
            _edge("learn", "curriculum"),
        ],
        "codes": {
            "curriculum": (
                "def run(ctx):\n"
                "    \"\"\"按已有能力生成『下一课』，难度只提高一点。\"\"\"\n"
                "    skills = ctx.state.get('skills') or []\n"
                "    nxt = ctx.llm(\n"
                "        f'总目标：{ctx.state.get(\"goal\") or ctx.text}\\n'\n"
                "        f'已掌握技能：{\", \".join(str(s)[:60] for s in skills) or \"无\"}\\n'\n"
                "        '生成下一个难度略高的具体任务，只输出这一句任务描述。')\n"
                "    ctx.state['lesson'] = nxt\n"
                "    ctx.emit('curriculum', {'lesson': str(nxt)[:100]})\n"
                "    return {'data': nxt}\n"
            ),
            "learn": (
                "def run(ctx):\n"
                "    \"\"\"成功就把这段代码收进技能库。\"\"\"\n"
                "    code = str(ctx.text)\n"
                "    skills = ctx.state.setdefault('skills', [])\n"
                "    skills.append(ctx.state.get('lesson') or '')\n"
                "    ctx.write_file(f\"skills/{len(skills)}.py\", code)\n"
                "    ctx.emit('skill_learned', {'total': len(skills)})\n"
                "    return {'data': ctx.text}\n"
            ),
        },
        "notes": "Voyager 的关键不是『写代码』，而是『技能会累积』——learn 节点必须落盘，"
                 "否则每次重开都从零开始，那就退化成普通代码 agent 了。",
    },

    # ------------------------------------------------------------------ #
    # OpenHands / SWE-agent：沙箱里的执行循环
    # ------------------------------------------------------------------ #
    {
        "id": "openhands",
        "name": "OpenHands",
        "framework": "langchain",
        "paradigm": "sandboxed act-observe loop",
        "summary": "在沙箱里用命令和文件编辑改变工作区，每步都看真实输出再决定下一步。",
        "behaviors": [
            "所有动作都在沙箱内执行，越权访问直接拒绝",
            "通过命令/文件编辑改变工作区，而不是只在对话里给建议",
            "每一步都读取真实执行输出再决定下一步",
            "出现明确的完成信号才停，否则一直循环",
        ],
        "nodes": [
            _node("task", "input", "任务"),
            _node("merge", "merger", "上下文"),
            _node("agent", "agent", "思考下一步", {"mode": "react", "max_steps": 10}),
            _node("gate", "router", "还要执行命令吗？", {
                "question": "判断当前是否需要再执行命令或改文件？需要回答 true，"
                            "任务已完成回答 false。",
                "max_loops": 12,
            }),
            _node("sandbox", "guardrail", "沙箱", {
                "rule": "命令只在工作目录内执行；越界路径直接拒绝",
            }),
            _node("bash", "shell", "执行命令"),
            _node("observe", "observation", "读取输出"),
            _node("out", "output", "交付结果"),
        ],
        "edges": [
            _edge("task", "merge"),
            _edge("merge", "agent"),
            _edge("agent", "gate"),
            _edge("gate", "sandbox", "true"),
            _edge("sandbox", "bash"),
            _edge("bash", "observe"),
            _edge("observe", "merge"),
            _edge("gate", "out", "false"),
        ],
        "codes": {
            "observe": (
                "def run(ctx):\n"
                "    \"\"\"把命令的 stdout/stderr 一起回给模型——报错也是信息。\"\"\"\n"
                "    out = str(ctx.text or '')\n"
                "    ctx.state.setdefault('history', []).append(out[:2000])\n"
                "    tail = out[-4000:] if len(out) > 4000 else out\n"
                "    return {'data': f'【执行输出】\\n{tail}'}\n"
            ),
        },
        "notes": "OpenHands 与纯对话 agent 的差别在于『观察的是真实系统输出』，"
                 "所以 observe 节点必须拿真实 stdout/stderr，不能自己编摘要。",
    },

    # ------------------------------------------------------------------ #
    # AutoGen：GroupChat + 发言选择
    # ------------------------------------------------------------------ #
    {
        "id": "autogen",
        "name": "AutoGen",
        "framework": "autogen",
        "paradigm": "group chat with speaker selection",
        "summary": "多个 agent 共享一段对话，由 manager 决定下一个谁发言，"
                   "直到命中终止条件。",
        "behaviors": [
            "所有 agent 共享同一段对话历史，不是各自独立上下文",
            "由 manager 决定下一个发言者，不是固定顺序轮转",
            "发言者可以调用工具（代码执行）后再回到群聊",
            "命中终止条件（完成词 / 轮次上限）才结束",
        ],
        "nodes": [
            _node("task", "input", "任务"),
            _node("manager", "supervisor", "群聊管理", {"max_rounds": 8}),
            _node("planner", "worker", "规划者", {"mode": "cot", "max_steps": 2}),
            _node("coder", "worker", "执行者", {"mode": "react", "max_steps": 6}),
            _node("sandbox", "guardrail", "沙箱", {
                "rule": "代理产生的代码只在隔离环境执行，不影响宿主",
            }),
            _node("exec", "code_interpreter", "代码执行"),
            _node("gate", "router", "是否终止？", {
                "question": "对话中是否出现 TERMINATE，或任务已明确完成？是则 true。",
                "max_loops": 8,
            }),
            _node("out", "output", "最终结果"),
        ],
        "edges": [
            _edge("task", "manager"),
            _edge("manager", "planner"),
            _edge("planner", "coder"),
            _edge("coder", "sandbox"),
            _edge("sandbox", "exec"),
            _edge("exec", "gate"),
            _edge("gate", "out", "true"),
            _edge("gate", "manager", "false"),
        ],
        "codes": {
            "manager": (
                "def run(ctx):\n"
                "    \"\"\"选下一个发言者：把当前对话和角色清单交给模型决定。\"\"\"\n"
                "    history = ctx.state.setdefault('chat_history', [])\n"
                "    history.append(str(ctx.text)[:2000])\n"
                "    pick = ctx.llm(\n"
                "        '可选发言者：planner（拆解需求）、coder（写并执行代码）。\\n'\n"
                "        '对话历史：\\n' + '\\n'.join(history[-6:]) +\n"
                "        '\\n只输出下一个发言者的名字，不要别的。')\n"
                "    speaker = 'coder' if 'coder' in str(pick).lower() else 'planner'\n"
                "    ctx.state['speaker'] = speaker\n"
                "    ctx.emit('speaker', {'next': speaker})\n"
                "    return {'data': '\\n'.join(history[-6:])}\n"
            ),
        },
        "notes": "AutoGen 的核心是『共享历史 + 动态选人』。如果改成固定顺序轮转，"
                 "就退化成流水线了，那是 MetaGPT。",
    },

    # ------------------------------------------------------------------ #
    # ChatDev：软件公司角色流水线（对话式）
    # ------------------------------------------------------------------ #
    {
        "id": "chatdev",
        "name": "ChatDev",
        "framework": "crewai",
        "paradigm": "software company pipeline",
        "summary": "把软件开发拆给 CEO / CTO / 程序员 / 测试四个角色，"
                   "每个阶段是一轮双人对话，产物传给下一阶段。",
        "behaviors": [
            "阶段固定：需求 → 设计 → 编码 → 测试，不跳阶段",
            "每个阶段是『甲方-乙方』双人对话，产出该阶段交付物",
            "测试不通过时只回退到编码阶段，不回退到设计",
            "最后汇总成可交付说明",
        ],
        "nodes": [
            _node("idea", "input", "产品想法"),
            _node("ceo", "agent", "CEO（提需求）", {"mode": "cot", "max_steps": 3}),
            _node("cto", "agent", "CTO（做设计）", {"mode": "cot", "max_steps": 3}),
            _node("dev", "agent", "程序员（写代码）", {"mode": "react", "max_steps": 8}),
            _node("qa", "agent", "测试（验功能）", {"mode": "react", "max_steps": 5}),
            _node("gate", "router", "测试通过？", {
                "question": "测试是否通过？通过回答 true，否则 false。",
                "max_loops": 3,
            }),
            _node("merge", "merger", "交付汇总"),
            _node("out", "output", "交付说明"),
        ],
        "edges": [
            _edge("idea", "ceo"),
            _edge("ceo", "cto"),
            _edge("cto", "dev"),
            _edge("dev", "qa"),
            _edge("qa", "gate"),
            _edge("gate", "merge", "true"),
            _edge("gate", "dev", "false"),
            _edge("merge", "out"),
        ],
        "codes": {},
        "notes": "ChatDev 和 MetaGPT 都是软件流水线，区别在 ChatDev 每个阶段是双人对话、"
                 "产物更依赖对话结论；MetaGPT 是结构化文档驱动。",
    },

    # ------------------------------------------------------------------ #
    # LangGraph：显式状态图 + 条件边 + checkpoint
    # ------------------------------------------------------------------ #
    {
        "id": "langgraph",
        "name": "LangGraph",
        "framework": "langchain",
        "paradigm": "explicit state graph",
        "summary": "状态是一份显式 schema，节点只返回状态增量，条件边决定下一个节点，"
                   "每步可 checkpoint 恢复。",
        "behaviors": [
            "状态是显式的（字段固定），节点只做增量更新而不是各存各的",
            "下一步走哪由条件边根据状态决定，不是写死的流程",
            "每步结束都落一次 checkpoint，可从任意一步恢复",
            "有明确的 END 节点作为终止",
        ],
        "nodes": [
            _node("input", "input", "输入"),
            _node("state", "state_store", "共享状态"),
            _node("think", "agent", "推理节点", {"mode": "react", "max_steps": 6}),
            _node("cond", "condition", "条件边", {
                "expression": "state.get('done') is True",
            }),
            _node("act", "tool", "动作节点"),
            _node("merge", "merger", "汇合"),
            _node("checkpoint", "memory", "检查点"),
            _node("out", "output", "END"),
        ],
        "edges": [
            _edge("input", "state"),
            _edge("state", "think"),
            _edge("think", "cond"),
            _edge("cond", "act", "true"),
            _edge("cond", "merge", "false"),
            _edge("act", "merge"),
            _edge("merge", "checkpoint"),
            _edge("checkpoint", "out"),
        ],
        "codes": {
            "cond": (
                "def run(ctx):\n"
                "    \"\"\"条件边：只看状态里的标记，不做语义判断。\"\"\"\n"
                "    state = ctx.state\n"
                "    done = bool(state.get('done'))\n"
                "    ctx.emit('edge', {'done': done})\n"
                "    return {'data': 'true' if done else 'false'}\n"
            ),
        },
        "notes": "LangGraph 的辨识度来自『显式状态 + 条件边』，"
                 "如果节点之间直接传文本、没有共享状态，那就不是图而是链。",
    },

    # ------------------------------------------------------------------ #
    # Dify：可视化工作流
    # ------------------------------------------------------------------ #
    {
        "id": "dify",
        "name": "Dify",
        "framework": "dify",
        "paradigm": "visual node workflow",
        "summary": "开始节点收变量，中间是知识检索 / LLM / 条件分支等固定节点，"
                   "按连线顺序执行到结束节点，可导出成 DSL。",
        "behaviors": [
            "开始节点声明输入变量，后续节点只能引用已声明的变量",
            "知识检索与 LLM 是两种独立节点，检索结果作为 LLM 的上下文变量",
            "条件分支按变量值走不同路径，不需要额外 agent",
            "整张流程可导出成 DSL，在 Dify 里导入运行",
        ],
        "nodes": [
            _node("start", "input", "开始（输入变量）"),
            _node("retrieve", "rag_retriever", "知识检索"),
            _node("llm", "llm", "LLM 节点"),
            _node("branch", "condition", "条件分支", {
                "expression": "len(state.get('context') or '') > 0",
            }),
            _node("answer", "formatter", "直接回答"),
            _node("end", "output", "结束"),
        ],
        "edges": [
            _edge("start", "retrieve"),
            _edge("retrieve", "branch"),
            _edge("branch", "llm", "true"),
            _edge("branch", "answer", "false"),
            _edge("llm", "end"),
            _edge("answer", "end"),
        ],
        "codes": {},
        "notes": "Dify 的流程是『变量驱动』而不是『对话驱动』，"
                 "所以它没有 agent 循环，靠条件分支覆盖不同情况。",
    },

    # ------------------------------------------------------------------ #
    # Coze：人设 + 插件 + 知识库
    # ------------------------------------------------------------------ #
    {
        "id": "coze",
        "name": "Coze",
        "framework": "langchain",
        "paradigm": "bot = persona + plugins + knowledge",
        "summary": "一个 Bot 由人设、插件、知识库三块拼成：先查知识库，"
                   "不够再调插件，最后按人设口吻作答。",
        "behaviors": [
            "人设是固定 prompt，决定口吻和边界，不随对话改变",
            "先检索知识库，命中就基于知识回答",
            "知识库答不了才调插件（联网/业务接口）",
            "多轮对话有记忆，能接上上文",
        ],
        "nodes": [
            _node("msg", "input", "用户消息"),
            _node("persona", "system_prompt", "人设", {
                "template": "你是{{name}}。风格：{{style}}。"
                            "不清楚就说不清楚，不要编造。",
            }),
            _node("kb", "rag_retriever", "知识库"),
            _node("gate", "router", "知识库够用吗？", {
                "question": "检索到的内容是否足以回答问题？够用回答 true，否则 false。",
                "max_loops": 3,
            }),
            _node("plugin", "tool", "插件调用"),
            _node("merge", "merger", "汇合"),
            _node("answer", "agent", "按人设作答", {"mode": "cot", "max_steps": 3}),
            _node("mem", "memory", "对话记忆"),
            _node("out", "output", "回复"),
        ],
        "edges": [
            _edge("msg", "persona"),
            _edge("persona", "kb"),
            _edge("kb", "gate"),
            _edge("gate", "merge", "true"),
            _edge("gate", "plugin", "false"),
            _edge("plugin", "merge"),
            _edge("merge", "answer"),
            _edge("answer", "mem"),
            _edge("mem", "out"),
        ],
        "codes": {},
        "notes": "Coze 与 Dify 的区别：Coze 是『Bot 优先』（人设 + 能力挂载），"
                 "Dify 是『流程优先』（节点连线决定行为）。",
    },

    # ------------------------------------------------------------------ #
    # n8n：触发器 + 节点链
    # ------------------------------------------------------------------ #
    {
        "id": "n8n",
        "name": "n8n",
        "framework": "langchain",
        "paradigm": "trigger-driven automation",
        "summary": "由触发器启动，节点按连线串行执行，每个节点的输出就是下一个的输入，"
                   "条件节点负责分流。",
        "behaviors": [
            "流程由触发器启动（webhook / 定时 / 手动），不是对话驱动",
            "节点严格串行，上一个的输出是下一个的输入",
            "条件节点按表达式分流，不走 LLM 判断",
            "没有 agent 循环，失败靠重试而不是重新规划",
        ],
        "nodes": [
            _node("trigger", "input", "触发器"),
            _node("fetch", "http_request", "调用接口"),
            _node("check", "condition", "条件判断", {
                "expression": "state.get('status') == 200",
            }),
            _node("transform", "formatter", "数据整形"),
            _node("notify", "http_request", "通知/写回"),
            _node("err", "error_handler", "失败处理"),
            _node("out", "output", "结束"),
        ],
        "edges": [
            _edge("trigger", "fetch"),
            _edge("fetch", "check"),
            _edge("check", "transform", "true"),
            _edge("check", "err", "false"),
            _edge("transform", "notify"),
            _edge("notify", "out"),
            _edge("err", "out"),
        ],
        "codes": {},
        "notes": "n8n 的节点是『数据管道』而不是『智能体』：没有规划、没有反思，"
                 "行为完全由连线决定。",
    },

    # ------------------------------------------------------------------ #
    # Flowise：可视化 RAG
    # ------------------------------------------------------------------ #
    {
        "id": "flowise",
        "name": "Flowise",
        "framework": "langchain",
        "paradigm": "visual rag pipeline",
        "summary": "文档加载 → 切分 → 向量化 → 入库 → 检索 → 拼 prompt → 回答，"
                   "每个环节是一个可连线组件。",
        "behaviors": [
            "知识先离线入库：加载、切分、向量化、写入向量库",
            "在线查询才走向量检索，检索结果作为上下文",
            "检索到的片段拼进 prompt，再交给模型作答",
            "整条链的顺序就是连线顺序，没有分支智能",
        ],
        "nodes": [
            _node("question", "input", "用户问题"),
            _node("loader", "doc_loader", "文档加载"),
            _node("split", "text_splitter", "文本切分"),
            _node("embed", "embedding", "向量化"),
            _node("store", "vector_store", "写入向量库"),
            _node("merge", "merger", "查询+索引"),
            _node("retrieve", "rag_retriever", "检索"),
            _node("answer", "llm", "回答"),
            _node("out", "output", "结果"),
        ],
        "edges": [
            _edge("question", "loader"),
            _edge("loader", "split"),
            _edge("split", "embed"),
            _edge("embed", "store"),
            _edge("store", "merge"),
            _edge("question", "merge"),
            _edge("merge", "retrieve"),
            _edge("retrieve", "answer"),
            _edge("answer", "out"),
        ],
        "codes": {},
        "notes": "把『入库』和『检索』放在同一条链上是为了可读；真实 Flowise 里"
                 "入库是独立的离线流程，只有检索那条链在线上跑。",
    },

    # ------------------------------------------------------------------ #
    # Langflow：组件线性链
    # ------------------------------------------------------------------ #
    {
        "id": "langflow",
        "name": "Langflow",
        "framework": "langchain",
        "paradigm": "component chain",
        "summary": "把 prompt 模板、模型、输出解析器当成可连线的组件，"
                   "按类型匹配输入输出，串成一条链。",
        "behaviors": [
            "每个组件有明确的输入/输出类型，类型不匹配的连线不成立",
            "prompt 模板负责拼变量，不负责推理",
            "模型组件只做生成，解析组件负责把文本转成结构化",
            "链是线性的，分支要显式加条件组件",
        ],
        "nodes": [
            _node("vars", "input", "输入变量"),
            _node("template", "prompt", "Prompt 模板", {
                "template": "请基于以下信息回答：\n{context}\n\n问题：{question}",
            }),
            _node("model", "llm", "模型"),
            _node("parser", "formatter", "输出解析"),
            _node("out", "output", "结构化结果"),
        ],
        "edges": [
            _edge("vars", "template"),
            _edge("template", "model"),
            _edge("model", "parser"),
            _edge("parser", "out"),
        ],
        "codes": {},
        "notes": "Langflow 是 LangChain 的可视化壳：组件 = LangChain 的 Runnable，"
                 "连线 = 管道。所以它是链不是图，没有循环。",
    },
]

BY_ID: Dict[str, Dict[str, Any]] = {item["id"]: item for item in ARCHITECTURES}

# 每个架构对应的画布级推理模式（顶部「模式」下拉框）。
# 放在这里而不是写进每条记录，是为了让「框架」和「模式」在一处对齐、便于核对。
MODE_BY_ID: Dict[str, str] = {
    "autogpt": "goal",            # 目标驱动：拆任务直到达成
    "metagpt": "sop",             # 标准作业流程：角色流水线
    "crewai": "sequential",       # 顺序接力：角色依次交付
    "deepseek-harness": "react",  # 工具调用循环
    "babyagi": "goal",            # 目标驱动：任务队列推进
    "camel": "two_agent",         # 双人对话：角色交替
    "voyager": "code_agent",      # 代码行动：写码执行学技能
    "openhands": "code_agent",    # 代码行动：沙箱里 bash/编辑
    "autogen": "group_chat",      # 群聊：共享历史 + 选人发言
    "chatdev": "sequential",      # 顺序接力：需求→设计→编码→测试
    "langgraph": "react",         # 状态图 + 条件边
    "dify": "workflow",           # 节点工作流
    "coze": "chatflow",           # 对话流
    "n8n": "workflow",            # 节点工作流
    "flowise": "rag",             # 检索增强
    "langflow": "rag",            # 组件链
}


def mode_of(arch: Dict[str, Any]) -> str:
    return arch.get("mode") or MODE_BY_ID.get(arch["id"], "")


def list_all() -> List[Dict[str, Any]]:
    return [{"id": a["id"], "name": a["name"], "framework": a["framework"],
             "mode": mode_of(a),
             "paradigm": a["paradigm"], "summary": a["summary"],
             "behavior_count": len(a["behaviors"])} for a in ARCHITECTURES]


def get(arch_id: str) -> Optional[Dict[str, Any]]:
    return BY_ID.get((arch_id or "").strip().lower())


def to_draft(arch: Dict[str, Any]) -> Dict[str, Any]:
    """转成 apply-draft 能吃的草稿（把 codes 合进节点）。"""
    nodes = []
    for node in arch["nodes"]:
        item = dict(node)
        code = (arch.get("codes") or {}).get(node["key"])
        if code:
            item["code"] = code
        nodes.append(item)
    return {"nodes": nodes, "edges": list(arch["edges"])}
