"""各个 Agent 框架支持的推理 / 协作模式。

前端顶部「模式」下拉会按所选框架给出对应的一组模式；
agent 节点的「推理模式」参数也从这份清单里取。

每条模式：
    value  代码里用的标识
    label  下拉里显示的名字
    group  分组（基础 / 推理 / 循环 / 规划 / 多智能体）
    desc   一句话说明它怎么工作、什么时候用
"""
from __future__ import annotations

from typing import Dict, List

# --------------------------------------------------------------------------- #
# 全部模式（各框架共用同一套定义，避免同一个词出现两种说法）
# --------------------------------------------------------------------------- #
ALL_MODES: List[Dict[str, str]] = [
    # ---- 基础 ----
    {"value": "simple", "label": "单次调用", "group": "基础",
     "desc": "一次模型调用直接返回，不循环不调工具，最快最省。"},
    {"value": "tool_call", "label": "函数调用", "group": "基础",
     "desc": "走原生 tool_calls 协议，模型决定调哪个工具，可单轮也可多轮。"},
    {"value": "structured", "label": "结构化输出", "group": "基础",
     "desc": "强制按给定 JSON Schema 输出，适合需要稳定字段的场景。"},

    # ---- 推理 ----
    {"value": "cot", "label": "CoT 思维链", "group": "推理",
     "desc": "让模型分步推理再给答案，不调工具；适合数学、逻辑、归因。"},
    {"value": "self_ask", "label": "Self-Ask", "group": "推理",
     "desc": "自己拆出子问题、逐个回答再汇总，适合多跳推理。"},
    {"value": "self_consistency", "label": "自洽投票", "group": "推理",
     "desc": "多次采样后取多数答案，用成本换准确率。"},
    {"value": "tot", "label": "Tree-of-Thoughts", "group": "推理",
     "desc": "同时展开多条思路并剪枝择优，成本最高，用于难题。"},

    # ---- 循环 ----
    {"value": "react", "label": "ReAct", "group": "循环",
     "desc": "思考 → 调工具 → 看结果 → 再思考，最通用的 Agent 循环。"},
    {"value": "goal", "label": "目标驱动", "group": "循环",
     "desc": "给定完成条件反复逼近，直到条件满足或达到上限。"},
    {"value": "reflexion", "label": "反思迭代", "group": "循环",
     "desc": "产出后自我批评再重做，质量优先于速度。"},

    # ---- 规划 ----
    {"value": "plan_execute", "label": "Plan-and-Execute", "group": "规划",
     "desc": "先出完整计划，再逐步执行；步骤明确的长任务最适合。"},
    {"value": "rewoo", "label": "ReWOO", "group": "规划",
     "desc": "先规划工具调用序列，再一次性执行，省掉中间的模型往返。"},
    {"value": "map_reduce", "label": "分治汇总", "group": "规划",
     "desc": "把任务拆成若干块并行处理，最后合并成一份结果。"},

    # ---- 多智能体 ----
    {"value": "supervisor", "label": "主管调度", "group": "多智能体",
     "desc": "一个主管把子任务分给多个 worker，最后汇总。"},
    {"value": "group_chat", "label": "群聊", "group": "多智能体",
     "desc": "多个角色在同一段对话里轮流发言，由管理者控制节奏。"},
    {"value": "sequential", "label": "顺序接力", "group": "多智能体",
     "desc": "多个 agent 按固定顺序交接，像流水线。"},
    {"value": "hierarchical", "label": "层级分派", "group": "多智能体",
     "desc": "管理者分配任务给成员并验收结果，比顺序更灵活。"},
    {"value": "parallel", "label": "并行处理", "group": "多智能体",
     "desc": "多个子任务同时跑，最后合并。"},
    {"value": "debate", "label": "辩论", "group": "多智能体",
     "desc": "正反方各执一词互相质疑，最后收敛或由裁判定论。"},
    {"value": "consensus", "label": "共识投票", "group": "多智能体",
     "desc": "多个 agent 各自给结论，按投票或一致性规则定案。"},
    {"value": "nested", "label": "嵌套对话", "group": "多智能体",
     "desc": "一个 agent 内部再开一段子对话，用来处理复杂子任务。"},
    {"value": "handoff", "label": "移交", "group": "多智能体",
     "desc": "当前 agent 判断该由别人处理时，把控制权交出去。"},
    {"value": "swarm", "label": "群体交接", "group": "多智能体",
     "desc": "一群 agent 按规则互相移交，没有固定中枢。"},
    {"value": "route", "label": "意图路由", "group": "多智能体",
     "desc": "先判断意图，再分给对应的专职 agent。"},

    # ---- 框架专有 ----
    {"value": "code_agent", "label": "代码行动", "group": "框架专有",
     "desc": "让模型用写代码的方式表达行动，能力最强但需要沙箱。"},
    {"value": "sop", "label": "标准作业流程", "group": "框架专有",
     "desc": "按 SOP 定义的角色顺序推进，流程固定可预期。"},
    {"value": "guardrails", "label": "护栏校验", "group": "框架专有",
     "desc": "在输入输出两侧加校验，不合规就拦下或重来。"},
    {"value": "workflow", "label": "节点工作流", "group": "框架专有",
     "desc": "按预设节点顺序执行，行为最可控，适合线上稳定场景。"},
    {"value": "chatflow", "label": "对话流", "group": "框架专有",
     "desc": "面向多轮对话的编排，带会话变量和分支。"},
    {"value": "managed", "label": "受管执行", "group": "框架专有",
     "desc": "由上层 agent 管理子 agent 的调用与生命周期。"},
]

MODE_INDEX: Dict[str, Dict[str, str]] = {m["value"]: m for m in ALL_MODES}

# --------------------------------------------------------------------------- #
# 各框架支持的模式（按各自的真实能力挑，不是简单照搬全集）
# --------------------------------------------------------------------------- #
FRAMEWORK_MODES: Dict[str, List[str]] = {
    "langchain": [
        "simple", "cot", "tool_call", "react", "plan_execute", "rewoo",
        "reflexion", "goal", "self_consistency", "tot", "supervisor", "map_reduce",
    ],
    "autogen": [
        "simple", "tool_call", "two_agent", "group_chat", "sequential", "nested",
        "debate", "reflexion", "code_agent", "handoff", "swarm", "guardrails",
    ],
    "crewai": [
        "simple", "sequential", "hierarchical", "parallel", "consensus",
        "debate", "map_reduce",
    ],
    "metagpt": [
        "sop", "sequential", "debate", "plan_execute", "reflexion",
    ],
    "agno": [
        "simple", "tool_call", "react", "reasoning", "route", "supervisor",
        "parallel", "workflow", "guardrails",
    ],
    "smolagents": [
        "code_agent", "tool_call", "react", "managed", "plan_execute",
    ],
    "semantic_kernel": [
        "simple", "tool_call", "plan_execute", "group_chat", "handoff", "route",
    ],
    "openai_agents": [
        "simple", "tool_call", "handoff", "guardrails", "structured",
        "supervisor", "parallel",
    ],
    "dify": [
        "chatflow", "workflow", "tool_call", "cot", "rag",
    ],
    "custom": [
        "simple", "cot", "tool_call", "react", "plan_execute", "goal",
        "reflexion", "sequential", "hierarchical", "debate", "handoff",
    ],
}

# 补几个上面引用到但清单里还没定义的
_EXTRA = [
    {"value": "two_agent", "label": "双人对话", "group": "多智能体",
     "desc": "一个执行者加一个代理用户交替发言，AutoGen 最基础的形态。"},
    {"value": "reasoning", "label": "显式推理", "group": "推理",
     "desc": "把推理步骤单独列出来再执行，便于检查和调试。"},
    {"value": "rag", "label": "检索增强", "group": "基础",
     "desc": "先检索知识库再回答，答案有据可依。"},
]
for _m in _EXTRA:
    if _m["value"] not in MODE_INDEX:
        ALL_MODES.append(_m)
        MODE_INDEX[_m["value"]] = _m


def modes_for(framework: str) -> List[Dict[str, str]]:
    """某个框架可选的模式，带完整描述。"""
    values = FRAMEWORK_MODES.get(framework) or FRAMEWORK_MODES["custom"]
    return [MODE_INDEX[v] for v in values if v in MODE_INDEX]


def default_mode(framework: str) -> str:
    """框架的默认模式。"""
    values = FRAMEWORK_MODES.get(framework) or FRAMEWORK_MODES["custom"]
    return values[0] if values else "simple"


def all_modes() -> List[Dict[str, str]]:
    return ALL_MODES
