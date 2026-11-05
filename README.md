# MineAgent · Agent 编排画布

> Agent 定制自由化，Agent 流程可视化，降低普罗大众使用 Agent 的门槛。

一个本地运行的前后端分离项目：在浏览器里用画布搭出工业级 Agent 流程，选框架自动生成架构图，
拖节点、连线、写代码、配模型，点「保存」就把整张画布编译成**一个可独立运行的 Python Agent 项目**，
点「运行」直接在你的机器上真实执行并流式回传每一步。

- 前端：React 18 + TypeScript + React Flow + Vite
- 后端：Python FastAPI + SQLite（零 ORM、零额外依赖）
- 存储：SQLite 存画布与配置；`projects/<画布名>/` 存生成出来的 Agent 项目
- 启动：双击 `start.bat`（或 `.\start.ps1`），一个端口，一个地址

---

## 快速开始

```powershell
# 方式一：双击 start.bat

# 方式二：命令行
.\start.ps1

# 指定端口 / 开发模式（前端 5173 热更新 + 后端 8000）
.\start.ps1 -Port 8080
.\start.ps1 -Dev
```

脚本会自动完成：Python 虚拟环境 → 后端依赖 → 前端依赖 → 前端构建 → 启动服务 → 打开浏览器。
默认地址 `http://127.0.0.1:8000`，同一局域网内其他设备可用 `http://<你的内网IP>:8000` 访问。

首次启动如果没有任何画布，会自动创建一张 LangChain 架构图。

**没有 API Key 也想跑通？** 另开一个窗口：

```powershell
.\.venv\Scripts\python.exe tools\mock_llm.py --port 8012
```

然后在「用户中心」把 Base URL 填 `http://127.0.0.1:8012/v1`、模型填 `mock-model`、Key 随便填，
整条链路（画布 → 代码 → 运行 → 事件流）就能完整跑起来。

---

## 界面与功能

![画布总览](docs/screenshots/01-canvas.png)

选中节点后可以编辑属性参数，也可以直接编辑它运行时真正执行的 Python 代码：

![节点代码编辑](docs/screenshots/03-code-editor.png)

点运行后，每个节点的执行过程、耗时、分支走向会实时回显，最终结果单独展示：

![运行面板](docs/screenshots/05-run.png)

右键空白画布可以搜出 110 种节点，从 `observation` 这类经典循环节点，到意图识别、查询改写、混合检索、重排、上下文拼装，再到 MCP、护栏、人工审批：

![节点面板](docs/screenshots/04-node-picker.png)

| 位置 | 功能 |
| --- | --- |
| 左上角下拉 | 切换画布、新增画布（可命名，不填则用默认名）、重命名、删除、打开项目目录 |
| 顶部「保存」 | 把画布落库，并实时生成 `projects/<画布>/` 下的全部代码（`Ctrl/Cmd + S`） |
| 顶部「↶ / ↷」 | 撤销 / 重做画布改动（`Ctrl+Z` / `Ctrl+Shift+Z` 或 `Ctrl+Y`），连续拖动合并成一步 |
| 顶部「⚠ 约束」 | 编排约束面板：内置规则 + 自定义规则，违规节点在画布上标红 |
| 顶部「运行」 | 编译并真实执行当前画布，执行过程流式回显到节点和运行面板 |
| 右上角下拉 | 选择 Agent 框架（LangChain/LangGraph、AutoGen、CrewAI…），切换后重建架构图 |
| 右上角「模型」 | 配置**这个画布**用的大模型与 API Key |
| 右上角「用户中心」 | 配置**整个项目**的全局 API Key（画布没单独配置时回退到这里） |
| 右键空白画布 | 弹出节点面板，110 种细粒度节点任选（带搜索）；新增后**按约束自动连线** |
| 右键任意节点 | 编辑代码逻辑 / 编辑属性参数 / 重命名标识 / 复制 / 删除 |
| 拖动节点右侧圆点 | 连到下个节点，编排顺序与循环（靠近目标节点会自动吸附，不用精确对准小圆点） |
| 右键节点「连线到其它节点」 | 不拖拽也能连线：先选节点，多端口节点再选出口，最后选目标 |
| 拖动节点本身 | 调整位置（吸附 16px 网格） |
| 选中后按 Delete | 删除节点或连线 |
| 悬停节点 | 浮层显示类型、推理模式、组织关系、参数、出口端口 |
| 单击节点 | 只选中（用于连线和缩放），**不会**切换右侧面板 |
| 右键任意节点 | 打开右侧「节点详情」并弹出操作菜单 |
| 双击节点 | 直接打开代码编辑器 |
| 右侧「AI 助手」 | 常驻对话面板，用用户中心的 key 解答框架 / 编排问题 |
| 节点属性「推理模式」 | 每个 agent 单独选 ReAct / Plan-and-Execute / Goal / Reflexion / ToolCall / Simple |
| 节点属性「组织关系」 | 指定上级、下级、平级 agent，改一边另一端自动同步 |
| 右键 agent →「配置模型」 | 给单个 agent 配独立模型与 API Key（key 加密入库，不写进项目文件） |
| 画布左上「🎨 背景」 | 底色（含透明）、上传背景图、填充方式与透明度、点阵网格 |
| 画布左上「⤢ 整理布局」 | 按上下游重新排布：输入最左、输出最右，分层排列、互不重叠、连线不交叉 |

画布支持缩放、平移、框选、MiniMap 导航。每个智能体强制要求一个 `input` 和一个 `output` 方块，
缺少时保存会被拦下并提示。

连线的几个细节：

- **连线会自动绕开节点**：直连被挡住时，自动改走节点群上方、下方或右侧，
  不会压在节点上，也不会被节点盖住；拖动节点后连线会实时重新绕行
- **同一对节点之间的多条边会自动上下错开**，不会叠成一条看不清
- **循环回边用虚线**（紫灰色），和正向流程线区分开；从右往左绕回去的边会被自动识别
- 分支标签（是 / 否 / 循环）渲染成小圆角 chip，跟着走线走
- **点击一条线，两端节点会一起高亮**，方便确认这条线是从哪连到哪
- **右键一条线**可以「修改起点 / 修改终点 / 重置弯曲 / 删除」，改成非法端点会被拦下
- **按住线中间的小圆点拖动**，可以调整这根线的弯曲走向；连接关系（source / target）不变
- 「⤢ 整理布局」按上下游重新排布，具体是：
  - **输入固定在最左、输出固定在最右**，中间按 BFS 分层从左到右铺开
  - 同层节点纵向排列并居中，层内按"上游重心的平均位置"排序，减少连线交叉
  - 层间距和行间距**按最宽/最高的节点自适应**（不小于 340 / 140），
    保证节点不重叠、线上分支名放得下
  - 排完自动 fitView

**新增节点会自动连线**，不用每次手动接：

| 情况 | 行为 |
| --- | --- |
| 先选中某个节点，再右键空白处新增 | 从选中节点连过来，并把原来那条边拆开——新节点**插到两者中间** |
| 没有选中节点时新增 | 连到**距离最近**的可接上游节点 |
| 新增的是工具类节点（tool / MCP / 检索…） | 优先挂到最近的 **agent 下游** |
| 新增的是 output | 接到当前**末端节点** |
| 新增的是 input，或附近找不到合法上游 | **不连线**，保持孤立（避免凭空造出违规） |

自动连线全程遵守约束：output 不会被当成上游、input 不会被当成下游、
不会重复连同一对节点。多端口节点（router 等）会优先选用还没占用的出口。

### 画布背景

画布默认是**透明**的（露出页面底色），也可以换成任意底色，或者上传自己的背景图：

![画布背景](docs/screenshots/06-background.png)

- **底色**：11 个预设色 + 取色器，随时「恢复透明」
- **背景图片**：PNG / JPG / WebP / GIF / BMP，≤ 12MB；四种填充方式（铺满 / 适应 / 平铺 / 居中），
  透明度 5%–100%，可随时移除
- **点阵网格**：可开关、可换颜色，只在编辑时做对齐参考
- 背景是「即改即存」的显示设置，改完立刻生效，不占用「未保存」标记；
  图片存在本机 `backend/data/backgrounds/`，不进 git，删除画布时一并清理

### Agent 推理模式与多 Agent 协作

**推理模式**：每个 agent 类节点（`agent` / `worker` / `supervisor` / AutoGen Tool Agent）
都能在属性面板里单独选推理策略，保存后写进 `agent.json` 的 `params.mode`：

| 模式 | 行为 |
| --- | --- |
| `react` | 思考 → 调工具 → 观察，循环直到能给出答案 |
| `plan_execute` | 先让模型列执行计划，再逐步执行，最后汇总 |
| `goal` | 围绕目标反复推进，每轮自评达成度，未达成就继续 |
| `reflexion` | 先出一版，自我批判后重写，适合对质量要求高的产出 |
| `tool_call` | 只做一轮工具调用，快、便宜 |
| `simple` | 单次推理，不循环不用工具 |

**组织关系**：在 agent 节点的属性面板里指定「上级」「下级」「平级」。
改一边另一边会自动同步——给 A 勾了 B 当上级，B 的下级列表里就会出现 A。
关系只表达组织与调度，不改变画布上的数据连线。

![多 Agent 组织关系](docs/screenshots/07-agent-org.png)

运行时这些关系会注入到节点上下文，代码里可以直接用：

```python
ctx.superior          # 我的上级 agent 名字
ctx.subordinates      # 我的下级 agent 名字列表
ctx.peers             # 平级 agent 名字列表
ctx.delegate("名字", 任务)   # 把活派给某个 agent，等它返回结果
```

`supervisor` 节点的默认模板就是「遍历 `ctx.subordinates` 逐个 delegate，再汇总」，
所以画一张 supervisor + 若干 worker、勾好上下级，就能直接跑出一套分层协作。

**节点级模型**：右键 agent 节点 →「配置模型 / API Key」，可以给这个 agent 单独指定
服务商、Base URL、模型名和 Key。它优先于画布配置，画布配置又优先于用户中心的全局配置。
Key 加密存在本机 `agent_models` 表，运行时通过环境变量 `MINEAGENT_KEY_<节点ID>` 注入子进程，
不会出现在 `agent.json` 或任何项目文件里。

### 内置 AI 助手

右侧那一列有两个 tab：「AI 助手」（默认）和「节点详情」。

![AI 助手](docs/screenshots/11-assistant.png)

- 用的是**你在「用户中心」里配的 key**，不需要额外配置
- 默认带上画布上下文：画布名、框架、节点清单、约束未通过的项、最近一次运行的报错、
  当前选中节点——所以可以直接问「我这张画布为什么跑不起来」
- 流式输出，可随时停止；「＋ 新对话」开一轮新的
- 它只做问答，不会替你改画布

没配 key 时面板会提示去用户中心配置，不会静默失败。

### 编排约束

画布不是随便连的。顶部「⚠ 约束」会跑一整套规则，违规节点在画布上标红并带 ⚠ 角标：

![编排约束](docs/screenshots/08-constraints.png)

**内置规则（18 条）**，分三类：

| 类别 | 规则 |
| --- | --- |
| 结构 | 有且只有一个输入节点、至少一个输出、输入不能有入边、输出不能有出边、无孤立节点、所有节点都能从输入到达、都能通向输出、不能自环、多入边需能合并 |
| 语义 | 分支节点两条出边都要连、循环节点必须有退出出口、有环就要有循环控制、工具节点应挂在 agent 下游、用工具的 agent 要连到 tool、技能节点必须有内容、命令执行前建议加护栏 |
| 数量 | 单画布节点数不超过 200 |

级别分三档：`error` 会**拦住运行**，`warn` 只提示，`info` 纯告知。

**自定义规则**（跟着画布保存）支持四种：

- **顺序约束**：某节点必须在某节点之后 / 之前
- **必须包含**：画布必须出现某类节点
- **禁止出现**：不允许出现某类节点
- **数量上限**：某类节点最多几个

每条可以选「拦截」或「提示」。内置规则是回边感知的——循环里 router 指回 agent 的那条边
不会被误判成「多入边」。

三个触发点：

1. 编辑时：停止操作 1.3 秒后自动复查，违规节点实时标红；
2. 保存时：照常保存（不耽误编辑中间态），但会把报告一并返回并提示还有几条没满足；
3. 运行时：`error` 级直接拦下并打开约束面板指出差在哪；确实要跑可以强制放行。


---

## 目录结构

```
MineAgent/
├─ start.ps1 / start.bat        # 一键启动
├─ backend/
│  ├─ app/
│  │  ├─ main.py                # FastAPI 入口 + 前端静态托管
│  │  ├─ config.py              # 路径与端口
│  │  ├─ db.py                  # SQLite（canvases / app_settings / runs）
│  │  ├─ security.py            # key 加密（HMAC 密钥流 + 校验标签）
│  │  ├─ node_registry.py       # 110 种节点类型注册表
│  │  ├─ node_templates.py      # 每种节点的默认代码模板
│  │  ├─ framework_templates.py # 10 个框架 + 各自的架构图模板 + 自动布局
│  │  ├─ codegen/generators.py  # 画布 → 独立 Agent 项目的代码生成
│  │  ├─ runtime/
│  │  │  ├─ runtime_sdk.py      # 节点可用的 ctx 能力（会被复制进每个项目）
│  │  │  └─ runner.py           # 内置图执行器（会被复制进每个项目）
│  │  └─ routers/               # canvases / run / projects / settings / meta
│  ├─ data/                     # mineagent.db、master.key、运行日志、背景图（不入库）
│  └─ requirements.txt
├─ frontend/
│  ├─ src/                      # React 应用
│  ├─ test/ui-smoke.mjs         # headless 浏览器交互测试
│  └─ dist/                     # 构建产物（后端自动托管）
├─ projects/                    # ★ 每个画布一个独立 Agent 项目
├─ tools/
│  ├─ mock_llm.py               # 本地 mock 模型服务
│  ├─ smoke_test.py             # 端到端冒烟测试
│  └─ api_test.py               # 后端边缘场景测试
└─ README.md
```

### 一个生成出来的项目长什么样

**`projects/` 下的每个文件夹都是一个完整的、可独立部署的 Agent 后端项目**：
把自己那个文件夹整个拷走就能跑，不依赖 MineAgent 平台，也不依赖数据库。

```
agent.py            # ← 核心：这一整张画布的框架原生代码
agent.json          # 画布图定义（节点、连线、参数、节点代码）
runner.py           # 零依赖预览执行器（不装框架也能在这里跑一遍）
runtime_sdk.py      # runner 用的运行时（只用标准库）
run.ps1 / run.sh    # 一键运行
config.json         # 模型配置（不含 key）
.env.example        # 脱离网页独立运行时，复制成 .env 填 key
skills/             # skill.md 技能文件
outputs/            # 运行产物
requirements.txt    # 该框架需要的依赖
```

**没有 `nodes/` 目录**。每个节点不是单独一个 `.py` 文件，而是 `agent.py` 里一个带
`═══` 标记的代码块——打开 `agent.py` 看到的就是这个 Agent 的完整实现：

```python
# ═══════════════════════════════════════════════════════════════
# 节点：Agent（ReAct）  (agent_3)  类型：agent
# ═══════════════════════════════════════════════════════════════

def agent_3(state: AgentState) -> dict:
    """Agent（ReAct） —— 推理模式：react，最多 6 步。"""
    agent = create_agent(
        model=llm,
        tools=TOOLS,
        system_prompt="你是一个能调用工具的智能体……",
    )
    result = agent.invoke(
        {"messages": [{"role": "user", "content": state.get("data", "")}]},
        config={"recursion_limit": 14},
    )
    messages = result.get("messages") or []
    answer = str(getattr(messages[-1], "content", "")) if messages else ""
    return {"data": answer}
```

**网页上节点的「代码逻辑」显示的就是这一段**——改那里，保存后 `agent.py` 里同一段跟着改。

不同类型节点对应不同的原生写法：

| 节点类型 | `agent.py` 里的写法 |
| --- | --- |
| `tool` / `web_search` | `@tool def xxx(query: str)`，自动汇总进 `TOOLS` |
| `agent` | `create_agent(model=llm, tools=TOOLS, system_prompt=...)` + `invoke` |
| `planner` / `observation` / `formatter` | `ChatPromptTemplate` + `llm.invoke(...)` |
| `router` | 返回 `{"route": "true"/"false"}`，图里接 `add_conditional_edges` |
| `retriever` | `vectorstore.as_retriever(...)` 的骨架代码 |
| `memory` | 简单的对话历史窗口 |
| `input` / `output` | 图的首尾函数 |

图本身用 **LangGraph 的 `StateGraph`** 组装：`builder.add_node(...)`、
`builder.add_edge(...)`、`add_conditional_edges(...)`、`builder.compile()`——
和你手写一个 LangGraph 项目没有区别。

`tool` 节点不会作为图里的一步：它的边会被"穿透"（`agent → tool → observation`
在代码里变成 `agent → observation`），工具函数由 agent 内部调用，这才是 ReAct 的正常用法。

### 代码和画布怎么保持同步

保存时会做这几件事，是**真正的增量修改**而不是每次推倒重写：

- **新增节点** → `agent.py` 里多一个带 `═══` 标记的函数块，图里多一行 `add_node` / `add_edge`
- **删除节点** → 对应的代码块和图里的 `add_node` / `add_edge` 一起被移除
- **改节点参数** → 只重新生成那一个块
- **手动改过代码** → 该节点标记为「已手改」，之后保存**保留你的版本**，不会被覆盖；
  点「恢复默认模板」可以丢弃手改重新生成
- 生成完会把每个块**写回画布数据**，所以网页上看到的就是 `agent.py` 里的真实代码

### 运行时跑的是真代码

点「运行」时：

1. 检查这张画布对应框架的依赖（`langchain` / `langchain-openai` / `langgraph`）是否就绪
2. **就绪 → 直接执行项目里的 `agent.py`**，跑的就是你在文件里看到的代码
3. 缺失 → 自动降级到零依赖的 `runner.py` 预览，运行面板上会标明「零依赖预览」

运行面板会显示当前是「真实运行 agent.py」还是「零依赖预览」。

AutoGen / CrewAI 两个框架同理：会生成 `AssistantAgent` + `GroupChat`、
`Agent` + `Task` + `Crew` 的原生写法。

自包含这块做了几件具体的事：

- `runtime_sdk.py` 与 `runner.py` 都复制进项目目录，只用 Python 标准库，
  **只要机器上有 Python 3.9+ 就能零依赖预览运行**，不需要 pip 装任何东西
- 执行器设置了 `sys.dont_write_bytecode`，跑完目录里不会冒 `__pycache__`
- 每次保存都会清掉残留的 `__pycache__`，目录始终是可直接打包的状态
- `skills/`、`outputs/` 带 `.gitkeep`，进 git 或压缩后目录结构不会丢

单独运行：

```powershell
cd "projects\竞品调研智能体"

# ① 零依赖预览：不装任何框架，用 runner 按图跑一遍
.\run.ps1 "帮我调研一下国产 Agent 编排平台"

# ② 真正跑原生代码：先装框架依赖，再走 agent.py
.\run.ps1 -Install
.\run.ps1 -UseFramework "帮我调研一下国产 Agent 编排平台"

# 或者手动
python agent.py --input "..."
```

实测：把整个目录拷到别的路径、用系统 Python（不带本项目的 .venv）执行
`run.ps1`，可以直接跑通。

---

## 运行原理

1. **保存**：后端把画布 JSON 转成 `agent.json`，为每个节点写出一个 `nodes/<name>.py`，
   再按当前框架生成 `agent.py` 与 `requirements.txt`。删掉的节点对应文件会被清理。
2. **运行**：后端用当前 Python 解释器拉起项目的 `runner.py` 子进程，
   通过 stdout 的 `@@EVENT@@{json}` 行回传事件，再以 SSE 推给浏览器。
3. **执行语义**（`runner.py`）：
   - 从 `input` 节点出发，沿边推进；
   - 多入边节点会先把**还没执行过的上游分支补齐**，再合并输入（fan-in）；
   - 返回 `true` / `false` / `loop` / `exit` 的多端口节点视为**路由节点**：
     走对应出边，且输入原样透传给下游（不改数据），这是循环与分支的基础；
   - 走回边按循环处理，每个节点最多访问 8 次（`agent.json` 里 `max_visits` 可调）。
4. **模型 key 从不落盘到项目目录**：运行时通过 `MINEAGENT_API_KEY` 环境变量注入子进程，
   `config.json` 里只有地址和模型名。

---

## 节点清单（110 种，13 类）

![节点库](docs/screenshots/09-node-library.png)

**RAG 全链路都是独立节点**，不是藏在某个"检索"黑盒里：

```text
索引侧：doc_loader → text_splitter → chunk_refiner → vector_indexer
查询侧：intent_recognizer → query_rewrite → query_expand → query_router
检索侧：hybrid_retriever（向量 + 关键词）→ reranker → context_builder → citation_formatter
质检侧：doc_grader → rag_evaluator
```

对应的 SDK 能力：`ctx.retrieve(mode="hybrid|vector|keyword")`、`ctx.vector_upsert/search`、
`ctx.rerank(query, docs, top_k)`、`ctx.build_context(docs, max_chars)`、`ctx.split_text()`、
`ctx.load_document()`（pdf/docx/md/csv）。

文档与多模态节点（`pdf_parser` / `ocr_extract` / `speech_to_text` / `image_analyzer`）依赖可选库，
没装时节点会返回一条可直接照做的安装提示，而不是把整个流程跑崩。

| 分类 | 节点 |
| --- | --- |
| 输入输出 | `input` 输入、`output` 输出 |
| 推理与决策 | `llm` LLM 推理、`agent` Agent 主体、`prompt` 提示词模板、`system_prompt` 系统提示词、`planner` 任务规划、`decomposer` 任务分解、`router` 条件路由、`reflector` 反思、`critic` 评审、`self_check` 自检、`evaluator` 质量评估 |
| RAG 与检索 | `intent_recognizer` 意图识别、`slot_filler` 槽位抽取、`query_rewrite` 查询改写、`query_expand` 查询扩展、`query_router` 查询路由、`doc_loader` 文档加载、`text_splitter` 文本切分、`chunk_refiner` 分块精炼、`vector_indexer` 向量入库、`hybrid_retriever` 混合检索、`bm25_search` 关键词检索、`reranker` 重排、`context_builder` 上下文拼装、`citation_formatter` 引用标注、`doc_grader` 相关性打分、`rag_evaluator` RAG 质量评估 |
| 数据与存储 | `db_write` 数据写入、`kv_store` 键值存储、`cache_lookup` 缓存查询、`cache_write` 缓存写入、`graph_query` 图关系查询 |
| 文档与多模态 | `pdf_parser` PDF 解析、`table_parser` 表格解析、`ocr_extract` OCR 文字识别、`image_analyzer` 图像理解、`speech_to_text` 语音转写 |
| 文本加工 | `translator` 翻译、`classifier` 分类器、`extractor` 实体抽取、`sentiment` 情感分析、`fact_checker` 事实核查、`deduplicator` 去重、`merger` 多路合并、`outline_builder` 大纲生成、`section_writer` 分段写作、`polisher` 润色、`title_generator` 标题生成 |
| 工具与能力 | `tool` 工具、`function` 自定义函数、`http_request` HTTP 请求、`web_search` 联网搜索、`code_interpreter` 代码解释器、`shell` 命令执行、`file_io` 文件读写、`sql_query` SQL 查询、`rag_retriever` 知识库检索、`embedding` 向量化、`vector_store` 向量库、`mcp_tool` MCP 工具、`browser` 网页抓取、`skill` 技能 |
| 记忆与状态 | `memory` 记忆、`state_store` 状态存取、`blackboard` 黑板、`history` 会话历史 |
| 流程控制 | `condition` 条件判断、`loop` 循环控制、`join` 分支汇聚、`delay` 延时、`subgraph` 子图调用、`human_approval` 人工审批、`guardrail` 护栏、`rate_limiter` 限流、`circuit_breaker` 熔断、`budget_guard` 预算控制、`cost_tracker` 成本统计 |
| 观察与反馈 | `observation` 观察、`review_observation` 观察复核、`format_observations` 观察格式化、`error_handler` 错误处理、`retry` 重试、`fallback` 兜底 |
| 多智能体协作 | `supervisor` 主管、`worker` 工作者、`group_chat` 群聊、`handoff` 转交、`debate` 辩论、`message_bus` 消息总线 |
| 后处理与交付 | `formatter` 格式化、`parser` 结构化解析、`summarizer` 摘要、`validator` 结构校验、`artifact_writer` 产物写出、`notification` 通知推送、`json_repair` JSON 修复、`markdown_render` Markdown 渲染 |
| 框架专有 | `langgraph_state` / `langgraph_node` / `langgraph_edge`、`autogen_assistant` / `autogen_user_proxy` / `autogen_group_chat` / `autogen_tool_agent`、`crewai_agent` / `crewai_task` / `crewai_crew` / `crewai_tool` |

每个节点在画布上都是独立可编辑的方块，点开就能改它的代码——没有藏在框架内部的"黑盒步骤"。

新增节点类型只需要在 `backend/app/node_registry.py` 的 `_DEFS` 里加一行，
并在 `node_templates.py`（或 `node_templates_ext.py`）里写默认代码，前端菜单会自动出现。

---

## 支持的框架

| 框架 | 状态 | 说明 |
| --- | --- | --- |
| LangChain / LangGraph | ✅ 可运行 | 画布 1:1 映射为 `StateGraph`，条件边对应多端口节点 |
| AutoGen | ✅ 可运行 | 节点映射为 `AssistantAgent` + `RoundRobinGroupChat` |
| CrewAI | ✅ 可运行 | 节点映射为 `Agent` / `Task` / `Crew` |
| MetaGPT、Agno、SmolAgents、Semantic Kernel、OpenAI Agents SDK、Dify Workflow | 🎨 架构图 | 选中后生成对应风格的架构图与代码骨架，暂不接原生执行 |

三个「可运行」框架的项目都会生成 `agent.py` 原生入口；
如果本机没装该框架，`agent.py` 会自动提示并回退到内置 `runner.py`，保证流程任何时候都能跑。

装框架依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install -r "projects\你的画布\requirements.txt"
```

---

## 配置模型

四种方式，优先级从高到低：

1. **节点级**：右键 agent 节点 →「配置模型 / API Key」（只影响这个 agent）；
2. **画布级**：右上角「模型」→ 填 Base URL / 模型名 / API Key（只影响这个画布）；
3. **全局**：右上角「用户中心」→ 配置整个项目默认使用的 key（兜底）；
4. **项目文件**：在 `projects/<画布>/.env` 里写 `MINEAGENT_API_KEY=sk-xxx`（脱离网页独立运行时用）。

填好可点「测试连接」立即验证。Key 加密存在本机 `backend/data/mineagent.db`，
接口只回显 `sk-****abcd` 形式的掩码，不返回明文。
节点级的 key 存在 `agent_models` 表，运行时只以 `MINEAGENT_KEY_<节点ID>` 环境变量的形式注入子进程。

**模型名不用手敲**：填完 Base URL 和 API Key 后，点输入框右边的「⟳ 获取列表」，
会调服务商的 `/v1/models` 把可用模型拉下来填进下拉候选（三处配置都支持：用户中心 / 画布模型 / 节点模型）。
如果服务商不提供这个接口，会提示你直接手填，输入框始终可以自由输入。

常见服务商的 Base URL 内置在预设里（OpenAI、DeepSeek、通义千问、智谱、月之暗面、Ollama 本地、自定义兼容地址）。

---

## 节点代码能用到什么

每个节点就是 `nodes/<name>.py` 里的一个 `run(ctx)` 函数，`ctx` 提供：

```python
ctx.text / ctx.input        # 上游输出（字符串 / 原始对象）
ctx.state                   # 跨节点共享的可变字典
ctx.params                  # 节点面板里配置的参数
ctx.llm(prompt, system=)    # 调大模型
ctx.llm_stream(...)         # 流式调大模型（token 会实时推到画布）
ctx.agent(task, tools, mode=)  # 内置 agent，mode 可选 react/plan_execute/goal/reflexion/tool_call/simple
ctx.superior                # 我的上级 agent 名字
ctx.subordinates            # 下级 agent 名字列表
ctx.peers                   # 平级 agent 名字列表
ctx.delegate(名字, 任务)     # 把任务派给某个 agent 并取回结果
ctx.json_prompt(...)        # 结构化输出
ctx.http(...) / ctx.search() / ctx.fetch_text() / ctx.mcp_call(...)
ctx.skill(name, inline)     # 读 skills/*.md 或直接用内联的 skill.md 内容
ctx.remember() / ctx.recall() / ctx.history()
ctx.retrieve() / ctx.embed() / ctx.vector_upsert() / ctx.vector_search()
ctx.exec_python() / ctx.shell() / ctx.read_file() / ctx.write_file() / ctx.query_sql()
ctx.log() / ctx.emit() / ctx.route()
```

`skill` 节点既可以直接把整份 `skill.md` 粘进代码，也可以在参数里填文件名，
再用 `ctx.skill()` 读取 `skills/` 下的文件。

---

## 测试

```powershell
# 后端 + 代码生成 + 真实执行（需要 mock 或真 key）
.\.venv\Scripts\python.exe tools\smoke_test.py

# 框架切换 / 改名 / 删除 / 文件浏览
.\.venv\Scripts\python.exe tools\api_test.py

# 编排约束：内置规则 / 自定义规则 / 运行拦截
.\.venv\Scripts\python.exe tools\constraint_test.py

# Agent 模式 / 多 agent 委派 / 节点级模型
.\.venv\Scripts\python.exe tools\feature_test.py

# 节点库与细粒度能力（110 节点、检索链路、新 SDK 能力）
.\.venv\Scripts\python.exe tools\granularity_test.py

# 浏览器端交互（右键菜单、代码编辑、保存、运行）
cd frontend
node test/ui-smoke.mjs
```

---

## 常见问题

**端口被占用**：`.\start.ps1 -Port 8080`。

**前端改了代码没生效**：`.\start.ps1 -Rebuild`，或 `cd frontend; npm run build`。

**中文在脚本里显示乱码**：`start.ps1` 已存为 UTF-8 with BOM；如果被编辑器改存成别的编码，
用 PowerShell 7 运行，或重新执行 `.\start.ps1 -NoBrowser` 检查提示信息。

**运行报「缺少模型 API Key」**：按上面「配置模型」任选一种方式配置。

**模型返回 401/404**：检查 Base URL 是否带 `/v1`（如 `https://api.deepseek.com/v1`），
以及模型名是否与服务商一致。

**想彻底重来**：删掉 `backend/data/` 和 `projects/` 下的内容，重新启动即可
（会生成新的加密主密钥，已保存的 key 需要重填）。

**网页上改了代码，但项目目录里被我手改过**：以画布为准——点保存会覆盖 `nodes/*.py`。
建议始终在网页里编辑节点代码，或者改完不要再到网页点保存。
