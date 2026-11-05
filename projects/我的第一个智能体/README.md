# 我的第一个智能体

- 画布 slug：`我的第一个智能体`
- 框架：**LangChain / LangGraph**（可运行）
- 节点数：10，连线数：10

## 运行

```bash
python agent.py --input "你的问题"
# 或只跑内置执行器
python runner.py --input "你的问题"
```

## 配置模型

1. 网页「用户中心」或画布设置里填 key（推荐，运行时自动注入）；
2. 或复制 `.env.example` 为 `.env` 并填写 `MINEAGENT_API_KEY`。

## 目录

```
agent.json       # 画布图定义（保存时自动覆盖）
agent.py         # 框架原生入口
runner.py        # 内置图执行器（任何画布都能跑）
runtime_sdk.py   # 节点可用的全部能力（ctx.*）
nodes/           # 每个节点一个 .py，网页里编辑的就是这里
skills/          # skill.md 技能文件
config.json      # 模型配置（不含 key）
outputs/         # 运行产物
```

## 节点清单

| 节点 | 类型 | 文件 |
| --- | --- | --- |
| 输入 Input | `input` | `nodes/input_1.py` |
| 任务规划 | `planner` | `nodes/planner_2.py` |
| Agent（ReAct） | `agent` | `nodes/agent_3.py` |
| 工具：search | `tool` | `nodes/search_tool.py` |
| 观察 Observation | `observation` | `nodes/observation_5.py` |
| 观察复核 Review | `review_observation` | `nodes/review_observation_6.py` |
| 继续 or 收敛 | `router` | `nodes/router_7.py` |
| 观察格式化 | `format_observations` | `nodes/format_observations_8.py` |
| 格式化输出 | `formatter` | `nodes/formatter_9.py` |
| 输出 Output | `output` | `nodes/output_10.py` |
