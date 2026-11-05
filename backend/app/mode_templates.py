"""33 个推理模式的画布节点模板。

选好「框架 + 模式」之后，画布直接生成对应的最小可用架构，
用户不用从空白画布开始搭。每个模板控制在 3-6 个节点，
只保留这个模式最核心的环节。

定义方式：
    nodes  -> (kind, 显示名, 参数覆盖, 角色)
    links  -> (起点下标, 终点下标, 出口名)  不写默认线性串联
    role   -> 用于前端高亮，input / output / main / aux 四类
"""
from __future__ import annotations

from typing import Any, Dict, List

# role: input 入口 / main 主处理 / aux 辅助（工具、观察、评审）/ output 出口
TPL: Dict[str, Dict[str, Any]] = {
    # ------------------------------------------------------------------ 基础
    "simple": {
        "name": "单次调用",
        "summary": "一个问题进、一次模型调用、一个答案出。最小的可用 Agent 骨架。",
        "nodes": [
            ("input", "输入", {}, "input"),
            ("llm", "LLM 推理", {"system": "你是严谨的助手，直接给出结论。"}, "main"),
            ("output", "输出", {}, "output"),
        ],
    },
    "tool_call": {
        "name": "函数调用",
        "summary": "模型自主决定调哪个工具，拿回结果后继续回答。",
        "nodes": [
            ("input", "输入", {}, "input"),
            ("agent", "Agent（函数调用）", {"mode": "tool_call", "max_steps": 4}, "main"),
            ("tool", "工具", {}, "aux"),
            ("output", "输出", {}, "output"),
        ],
    },
    "structured": {
        "name": "结构化输出",
        "summary": "强制模型按固定字段输出，适合下游要解析 JSON 的场景。",
        "nodes": [
            ("input", "输入", {}, "input"),
            ("llm", "结构化抽取", {"system": "只输出 JSON，不要任何解释文字。"}, "main"),
            ("formatter", "格式化", {"format": "json"}, "aux"),
            ("output", "输出", {}, "output"),
        ],
    },

    # ------------------------------------------------------------------ 推理
    "cot": {
        "name": "CoT 思维链",
        "summary": "先让模型分步推理，再收敛成最终答案；不调工具。",
        "nodes": [
            ("input", "输入", {}, "input"),
            ("llm", "分步推理", {"system": "先分步骤推理，最后单独一行给出结论。"}, "main"),
            ("output", "输出", {}, "output"),
        ],
    },
    "self_ask": {
        "name": "Self-Ask",
        "summary": "自己拆子问题、逐个回答，再把答案拼起来；适合多跳推理。",
        "nodes": [
            ("input", "输入", {}, "input"),
            ("decomposer", "拆子问题", {}, "main"),
            ("llm", "逐题回答", {"system": "逐个回答上面列出的子问题。"}, "aux"),
            ("formatter", "汇总", {}, "aux"),
            ("output", "输出", {}, "output"),
        ],
    },
    "self_consistency": {
        "name": "自洽投票",
        "summary": "同一问题多次采样，取出现次数最多的答案。",
        "nodes": [
            ("input", "输入", {}, "input"),
            ("llm", "采样 A", {"temperature": 0.8}, "aux"),
            ("llm", "采样 B", {"temperature": 0.8}, "aux"),
            ("llm", "采样 C", {"temperature": 0.8}, "aux"),
            ("merge", "投票汇总", {}, "main"),
            ("output", "输出", {}, "output"),
        ],
        "links": [[0, 1], [0, 2], [0, 3], [1, 4], [2, 4], [3, 4], [4, 5]],
    },
    "tot": {
        "name": "Tree-of-Thoughts",
        "summary": "同时展开多条思路，评估后保留最优的一条继续。",
        "nodes": [
            ("input", "输入", {}, "input"),
            ("llm", "展开思路", {"system": "给出 3 条不同的解题路径，每条一句话。"}, "main"),
            ("evaluator", "评估打分", {}, "aux"),
            ("llm", "沿最优路径求解", {}, "aux"),
            ("output", "输出", {}, "output"),
        ],
    },

    # ------------------------------------------------------------------ 循环
    "react": {
        "name": "ReAct",
        "summary": "思考 → 调工具 → 看结果 → 再思考，最通用的 Agent 循环。",
        "nodes": [
            ("input", "输入", {}, "input"),
            ("agent", "Agent（ReAct）", {"mode": "react", "max_steps": 6}, "main"),
            ("tool", "工具", {}, "aux"),
            ("observation", "观察", {}, "aux"),
            ("output", "输出", {}, "output"),
        ],
        "links": [[0, 1], [1, 2], [2, 3], [3, 1], [1, 4]],
    },
    "goal": {
        "name": "目标驱动",
        "summary": "给定完成条件反复逼近，直到条件满足或达到上限。",
        "nodes": [
            ("input", "输入", {}, "input"),
            ("agent", "Agent（目标驱动）", {"mode": "goal", "max_steps": 6}, "main"),
            ("evaluator", "完成度判断", {}, "aux"),
            ("condition", "达标了吗", {"expression": "score >= 0.8"}, "aux"),
            ("output", "输出", {}, "output"),
        ],
        "links": [[0, 1], [1, 2], [2, 3], [3, 4, "true"], [3, 1, "false"]],
    },
    "reflexion": {
        "name": "反思迭代",
        "summary": "先产出，再自我批评，按批评意见重做，直到问题清单清空。",
        "nodes": [
            ("input", "输入", {}, "input"),
            ("agent", "生成", {"mode": "simple"}, "main"),
            ("critic", "评审", {}, "aux"),
            ("condition", "还需要改吗", {"expression": "issues > 0"}, "aux"),
            ("output", "输出", {}, "output"),
        ],
        "links": [[0, 1], [1, 2], [2, 3], [3, 4, "true"], [3, 1, "false"]],
    },

    # ------------------------------------------------------------------ 规划
    "plan_execute": {
        "name": "Plan-and-Execute",
        "summary": "先出完整计划，再按步骤逐步执行，最后汇总。",
        "nodes": [
            ("input", "输入", {}, "input"),
            ("planner", "任务规划", {}, "main"),
            ("agent", "按计划执行", {"mode": "plan_execute"}, "aux"),
            ("formatter", "整理结果", {}, "aux"),
            ("output", "输出", {}, "output"),
        ],
    },
    "rewoo": {
        "name": "ReWOO",
        "summary": "先把要调的工具一次性规划好，再批量执行，省掉中间往返。",
        "nodes": [
            ("input", "输入", {}, "input"),
            ("planner", "规划工具序列", {"system": "只输出要调用的工具和参数，一行一个。"}, "main"),
            ("tool", "批量执行工具", {}, "aux"),
            ("formatter", "融合结果", {}, "aux"),
            ("output", "输出", {}, "output"),
        ],
    },
    "map_reduce": {
        "name": "分治汇总",
        "summary": "大任务切成若干块并行处理，最后合并成一份结论。",
        "nodes": [
            ("input", "输入", {}, "input"),
            ("decomposer", "切分任务", {}, "main"),
            ("llm", "处理分片 A", {}, "aux"),
            ("llm", "处理分片 B", {}, "aux"),
            ("merge", "合并", {}, "aux"),
            ("output", "输出", {}, "output"),
        ],
        "links": [[0, 1], [1, 2], [1, 3], [2, 4], [3, 4], [4, 5]],
    },

    # ------------------------------------------------------------------ 多智能体
    "supervisor": {
        "name": "主管调度",
        "summary": "一个主管把子任务分给 worker，收齐结果后统一回复。",
        "nodes": [
            ("input", "输入", {}, "input"),
            ("supervisor", "主管", {}, "main"),
            ("worker", "Worker", {}, "aux"),
            ("merge", "汇总", {}, "aux"),
            ("output", "输出", {}, "output"),
        ],
        "links": [[0, 1], [1, 2], [2, 3], [1, 3], [3, 4]],
    },
    "group_chat": {
        "name": "群聊",
        "summary": "多个角色在同一段对话里轮流发言，由管理者控制节奏。",
        "nodes": [
            ("input", "输入", {}, "input"),
            ("group_chat", "群聊", {}, "main"),
            ("agent", "参与者 A", {"mode": "simple"}, "aux"),
            ("formatter", "收敛结论", {}, "aux"),
            ("output", "输出", {}, "output"),
        ],
    },
    "sequential": {
        "name": "顺序接力",
        "summary": "多个 agent 按固定顺序交接，前一个的产出是后一个的输入。",
        "nodes": [
            ("input", "输入", {}, "input"),
            ("agent", "第一棒", {"mode": "simple"}, "main"),
            ("agent", "第二棒", {"mode": "simple"}, "aux"),
            ("agent", "第三棒", {"mode": "simple"}, "aux"),
            ("output", "输出", {}, "output"),
        ],
    },
    "hierarchical": {
        "name": "层级分派",
        "summary": "管理者分配任务、成员执行、评审验收，比顺序更灵活。",
        "nodes": [
            ("input", "输入", {}, "input"),
            ("supervisor", "管理者", {}, "main"),
            ("worker", "执行者", {}, "aux"),
            ("critic", "验收", {}, "aux"),
            ("output", "输出", {}, "output"),
        ],
        "links": [[0, 1], [1, 2], [2, 3], [3, 1], [3, 4]],
    },
    "parallel": {
        "name": "并行处理",
        "summary": "多个子任务同时跑，最后合并。",
        "nodes": [
            ("input", "输入", {}, "input"),
            ("decomposer", "拆并行分支", {}, "main"),
            ("worker", "分支 A", {}, "aux"),
            ("worker", "分支 B", {}, "aux"),
            ("merge", "合并", {}, "aux"),
            ("output", "输出", {}, "output"),
        ],
        "links": [[0, 1], [1, 2], [1, 3], [2, 4], [3, 4], [4, 5]],
    },
    "debate": {
        "name": "辩论",
        "summary": "正反方各执一词、互相质疑，最后由裁判给结论。",
        "nodes": [
            ("input", "输入", {}, "input"),
            ("agent", "正方", {"mode": "simple", "system_prompt": "你是正方，为给定立场辩护。"}, "aux"),
            ("agent", "反方", {"mode": "simple", "system_prompt": "你是反方，找出对方论据的漏洞。"}, "aux"),
            ("critic", "裁判", {}, "main"),
            ("output", "输出", {}, "output"),
        ],
        "links": [[0, 1], [0, 2], [1, 3], [2, 3], [3, 4]],
    },
    "consensus": {
        "name": "共识投票",
        "summary": "多个 agent 各自给结论，按投票规则定案。",
        "nodes": [
            ("input", "输入", {}, "input"),
            ("worker", "成员 A", {}, "aux"),
            ("worker", "成员 B", {}, "aux"),
            ("merge", "投票定案", {}, "main"),
            ("output", "输出", {}, "output"),
        ],
        "links": [[0, 1], [0, 2], [1, 3], [2, 3], [3, 4]],
    },
    "nested": {
        "name": "嵌套对话",
        "summary": "主 agent 把复杂子任务交给内部的子 agent 处理完再继续。",
        "nodes": [
            ("input", "输入", {}, "input"),
            ("agent", "主 Agent", {"mode": "react"}, "main"),
            ("agent", "子 Agent", {"mode": "simple"}, "aux"),
            ("formatter", "整合", {}, "aux"),
            ("output", "输出", {}, "output"),
        ],
    },
    "handoff": {
        "name": "移交",
        "summary": "当前 agent 判断该由别人处理时，把控制权交出去。",
        "nodes": [
            ("input", "输入", {}, "input"),
            ("agent", "前台 Agent", {"mode": "simple"}, "main"),
            ("router", "该谁处理", {"question": "这个问题需要转交给专职 agent 吗？"}, "aux"),
            ("agent", "专职 Agent", {"mode": "simple"}, "aux"),
            ("output", "输出", {}, "output"),
        ],
        "links": [[0, 1], [1, 2], [2, 3, "true"], [2, 4, "false"], [3, 4]],
    },
    "swarm": {
        "name": "群体交接",
        "summary": "一群 agent 按规则互相移交，没有固定中枢。",
        "nodes": [
            ("input", "输入", {}, "input"),
            ("agent", "Agent A", {"mode": "simple"}, "main"),
            ("agent", "Agent B", {"mode": "simple"}, "aux"),
            ("agent", "Agent C", {"mode": "simple"}, "aux"),
            ("output", "输出", {}, "output"),
        ],
    },
    "route": {
        "name": "意图路由",
        "summary": "先判断意图，再交给对应的专职 agent。",
        "nodes": [
            ("input", "输入", {}, "input"),
            ("router", "意图识别", {"question": "用户是想咨询问题，还是要执行操作？"}, "main"),
            ("agent", "咨询 Agent", {"mode": "simple"}, "aux"),
            ("agent", "执行 Agent", {"mode": "tool_call"}, "aux"),
            ("output", "输出", {}, "output"),
        ],
        "links": [[0, 1], [1, 2, "true"], [1, 3, "false"], [2, 4], [3, 4]],
    },
    "two_agent": {
        "name": "双人对话",
        "summary": "一个执行者和一个代理用户交替发言，AutoGen 最基础的形态。",
        "nodes": [
            ("input", "输入", {}, "input"),
            ("agent", "Assistant", {"mode": "simple"}, "main"),
            ("agent", "代理用户", {"mode": "simple", "system_prompt": "你扮演提出需求的用户，检查结果并追问。"}, "aux"),
            ("formatter", "收敛", {}, "aux"),
            ("output", "输出", {}, "output"),
        ],
        "links": [[0, 1], [1, 2], [2, 1], [1, 3], [3, 4]],
    },

    # ------------------------------------------------------------------ 框架专有
    "code_agent": {
        "name": "代码行动",
        "summary": "模型用写代码的方式表达行动，检查后交给执行器跑。",
        "nodes": [
            ("input", "输入", {}, "input"),
            ("agent", "Agent（代码行动）", {"mode": "react"}, "main"),
            ("self_check", "代码安全检查", {}, "aux"),
            ("code_interpreter", "代码执行", {}, "aux"),
            ("observation", "观察输出", {}, "aux"),
            ("output", "输出", {}, "output"),
        ],
        "links": [[0, 1], [1, 2], [2, 3], [3, 4], [4, 1], [1, 5]],
    },
    "sop": {
        "name": "标准作业流程",
        "summary": "按固定角色顺序推进：分析 → 执行 → 复核，流程可预期。",
        "nodes": [
            ("input", "输入", {}, "input"),
            ("agent", "分析师", {"mode": "simple"}, "main"),
            ("agent", "执行者", {"mode": "simple"}, "aux"),
            ("critic", "复核", {}, "aux"),
            ("output", "输出", {}, "output"),
        ],
    },
    "guardrails": {
        "name": "护栏校验",
        "summary": "输入先过一遍校验，输出再过一遍，不合规就拦下。",
        "nodes": [
            ("input", "输入", {}, "input"),
            ("condition", "输入校验", {"expression": "length <= 4000"}, "aux"),
            ("agent", "Agent", {"mode": "simple"}, "main"),
            ("self_check", "输出校验", {}, "aux"),
            ("output", "输出", {}, "output"),
        ],
        "links": [[0, 1], [1, 2, "true"], [1, 4, "false"], [2, 3], [3, 4]],
    },
    "workflow": {
        "name": "节点工作流",
        "summary": "按预设节点顺序执行，行为最可控，适合线上稳定场景。",
        "nodes": [
            ("input", "输入", {}, "input"),
            ("llm", "处理 1", {}, "main"),
            ("llm", "处理 2", {}, "aux"),
            ("formatter", "输出整理", {}, "aux"),
            ("output", "输出", {}, "output"),
        ],
    },
    "chatflow": {
        "name": "对话流",
        "summary": "面向多轮对话的编排：先带上会话记忆，再回答。",
        "nodes": [
            ("input", "输入", {}, "input"),
            ("memory", "会话记忆", {}, "aux"),
            ("llm", "回答", {"system": "结合会话历史回答，必要时追问。"}, "main"),
            ("output", "输出", {}, "output"),
        ],
    },
    "managed": {
        "name": "受管执行",
        "summary": "上层 agent 负责拆分和调度，子 agent 只做具体活。",
        "nodes": [
            ("input", "输入", {}, "input"),
            ("supervisor", "管理 Agent", {}, "main"),
            ("worker", "受管 Agent", {}, "aux"),
            ("merge", "收口", {}, "aux"),
            ("output", "输出", {}, "output"),
        ],
        "links": [[0, 1], [1, 2], [2, 3], [1, 3], [3, 4]],
    },
    "reasoning": {
        "name": "显式推理",
        "summary": "把推理步骤单独列出来再执行，便于检查和调试。",
        "nodes": [
            ("input", "输入", {}, "input"),
            ("llm", "推理步骤", {"system": "把推理过程拆成编号步骤，逐步说明依据。"}, "main"),
            ("self_check", "检查推理", {}, "aux"),
            ("formatter", "整理", {}, "aux"),
            ("output", "输出", {}, "output"),
        ],
    },
    "rag": {
        "name": "检索增强",
        "summary": "先从知识库检索，再把检索结果作为依据回答，答案有出处。",
        "nodes": [
            ("input", "输入", {}, "input"),
            ("rag_retriever", "检索", {}, "main"),
            ("llm", "基于资料回答", {"system": "只根据给定资料回答，资料里没有就说不知道。"}, "aux"),
            ("formatter", "附上引用", {}, "aux"),
            ("output", "输出", {}, "output"),
        ],
    },
}


def template_for(mode: str) -> Dict[str, Any]:
    return TPL.get(mode) or TPL["react"]


def template_summary(mode: str) -> Dict[str, Any]:
    t = TPL.get(mode)
    if not t:
        return {"mode": mode, "name": mode, "summary": "", "node_count": 0}
    return {
        "mode": mode,
        "name": t["name"],
        "summary": t["summary"],
        "node_count": len(t["nodes"]),
    }


def all_templates() -> Dict[str, Dict[str, Any]]:
    return {k: template_summary(k) for k in TPL}


# --------------------------------------------------------------------------- #
# 把模板变成画布图
# --------------------------------------------------------------------------- #
NODE_GAP = 380


def build_mode_graph(mode: str, framework: str = "langchain") -> Dict[str, Any]:
    """按模式模板生成一张完整的画布图（节点 + 连线 + 位置）。"""
    from .node_registry import get_node_type

    t = template_for(mode)
    specs = t["nodes"]
    nodes: List[Dict[str, Any]] = []
    for i, (kind, label, params, role) in enumerate(specs, 1):
        meta = get_node_type(kind)
        defaults = {p["key"]: p.get("default") for p in meta.get("params", [])}
        merged = {**defaults, **(params or {})}
        nodes.append({
            "id": f"n{i}",
            "type": "agent",
            "position": {"x": (i - 1) * NODE_GAP, "y": 0},
            "data": {
                "kind": kind,
                "label": label or meta["label"],
                "name": f"{kind}_{i}",
                "description": meta.get("description", ""),
                "code": "",
                "language": "python",
                "params": merged,
                "role": role,
            },
        })

    links = t.get("links") or [[i, i + 1] for i in range(len(specs) - 1)]
    edges: List[Dict[str, Any]] = []
    for idx, link in enumerate(links):
        src, dst = link[0], link[1]
        handle = link[2] if len(link) > 2 else "out"
        edges.append({
            "id": f"e{src}_{handle}_{dst}_{idx}",
            "source": f"n{src + 1}",
            "target": f"n{dst + 1}",
            "sourceHandle": handle,
            "targetHandle": "in",
            "type": "agent",
            "label": handle if handle != "out" else None,
            "data": {"branch": handle if handle != "out" else None},
        })

    return {
        "nodes": nodes,
        "edges": edges,
        "viewport": {"x": 0, "y": 0, "zoom": 0.75},
        "background": {},
        "framework": framework,
        "mode": mode,
        "name": t["name"],
        "summary": t["summary"],
    }
