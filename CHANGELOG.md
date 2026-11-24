# 更新记录

只记"做了什么、修了什么"，产品介绍和使用方法看 [README.md](README.md)。
日期为提交日期，同一日期内的条目按实现顺序排列。

---

## 2026-11-23 · 重排模型

主题是**重排模型**：画布配置原来只有「向量模型 / 向量库」，检索出来只能按向量相似度排序，
这次把「召回」和「排序」拆开，补上第四类 provider。

### 新增

- **重排模型（rerank）作为一类画布级 provider**
  - [`catalog_rerank.py`](backend/app/providers/catalog_rerank.py)：9 家厂商 ——
    Cohere Rerank、Jina Reranker、硅基流动（bge-reranker / Qwen3-Reranker）、
    阿里云百炼（gte-rerank）、Voyage AI、TEI / vLLM / Xinference 本地自部署，
    以及任意 OpenAI 风格 `/rerank` 网关
  - [`rerank.py`](backend/app/providers/rerank.py)：五类协议（openai_rerank / cohere /
    voyage / dashscope / tei），把各家不同的请求字段和分数名归一成
    `{index, score, text}`，按分数倒序返回
  - 和另外三类一样：密钥单独加密落库、接口只回掩码、支持没保存的草稿直接「连接测试」、
    画布内可配多套并设默认
  - 画布配置弹窗多一个「重排模型」页签；助手 `upsert_provider` 的 kind 也支持 rerank

- **运行时接入**
  - `ctx.rerank` 优先走配置好的重排模型（cross-encoder，看的是 query 与片段的交互）；
    没配或调用失败时打一条 warn，回退到原来的「对话模型打分 → 向量余弦」
  - 新增 `ctx.has_rerank`、项目级 `project_rerank()`；`config.json` 多出 `rerank` 段，
    密钥走 `MINEAGENT_RERANK_KEY`（第二个实例是 `_2`，以此类推）
  - 重排节点参数多一个「重排模型」下拉：跟随画布默认 / 指定某个实例

### 修复

- **重排节点的原生代码一直是占位**：`reranker` 之前落在 `_block_generic`，
  生成出来的 `agent.py` 只做一次模型调用，和画布上看到的「重排」不是一回事。
  现在生成真正的重排代码（`project_rerank`），配没配重排模型都能跑

---

## 2026-11-23

主题是**知识库**：从零加了一条「上传文档 → 切分 → 向量化 → 检索」的完整链路。

### 新增

- **知识库**（全局，不属于画布）
  - `knowledge_bases` 表 + [`knowledge.py`](backend/app/knowledge.py)：
    创建 / 上传 / 建索引 / 检索 / 删除，向量模型和向量库由知识库自带，
    不依赖某张画布的 provider
  - 三种创建入口：**即用型**（直接上传建库）、**自定义**（先选模板再调分段）、
    **连接外部知识库**（填地址 + 密钥接入 Dify 这类已有系统）
  - 三步向导：选数据源 → 分段与向量配置 → 处理并完成
  - 分段支持自定义标识符 / 最大长度 / 重叠长度，先按分隔符保留语义边界，
    再把小段拼到接近上限，相邻块留重叠
  - 外部知识库接入：向配置地址 POST `{query, top_k}`，能解析
    `records[].segment.content`（Dify）、`results[]`、`data[]` 等多种返回结构
  - 密钥单独加密存（embedding / vector / 外部接口三处），接口只回
    `has_*_key`，不返回明文

### 修复

- **知识库弹窗没渲染模型预设**：catalog 里每个 provider 都带 `models` 清单
  （含 BGE 全家桶），画布配置的 provider 面板会渲染成下拉，但知识库弹窗只渲染了
  `fields`，模型变成空文本框，用户得自己背 `BAAI/bge-m3` 这种名字。
  改成下拉并带上维度标注，厂商下拉也按「进程内 / 本地 / 云」分组

---

## 2026-11-18 · 助手 Agent 化与源码分析

这一版把 AI 助手从「单轮问答」改成**能调工具的 Agent**，并加了「按架构画图」和「按源码画图」。

### 新增

- **AI 助手 Agent 化**
  - 自己实现流式 Agent 循环（`assistant_agent.py`），支持多轮工具调用，最多 6 步，
    不引 langchain——这个循环足够简单，自己写更好控制
  - **读工具自动执行，写工具一律挂起**：写工具返回 `__pending__`，前端渲染待确认卡片，
    用户点「应用」才落地；回给模型的话是「操作已生成，等用户确认后才生效」
  - 工具共 20 个：读 11 个（画布/配置/节点文档/运行日志/约束/记忆/架构指纹/源码扫描），
    写 9 个（增量改画布、整张替换、改服务/模型/模式/框架/provider、按指纹生成、运行）
  - **密钥边界**：助手读不到也写不了 API Key，`get_config` 只返回 `has_key`

- **助手对话的记忆与压缩**
  - 短期：会话内最近 20 条
  - 长期：`assistant_memories` 表，按画布隔离，`remember`/`recall` 工具读写，
    字符二元组重叠度检索（不依赖向量模型），近重复（>0.85）更新而非新增
  - 压缩：对话超过 30 条时把早期内容压成摘要，只留最近 10 条；摘要存在
    `assistant_chats.summary` 里，刷新后仍有效
  - 对话按画布隔离：切画布清空、恢复该画布自己的对话；跨画布续写会被拒绝

- **架构指纹库**（`architectures.py`，16 个项目）
  - 每个指纹含行为特征（可验证）、节点拓扑、关键节点代码
  - 已收录：AutoGPT、BabyAGI、MetaGPT、CrewAI、CAMEL、Voyager、OpenHands、AutoGen、
    ChatDev、LangGraph、DeepSeek Harness、Dify、Coze、n8n、Flowise、Langflow
  - 每个指纹绑定推荐的框架与推理模式，生成画布时**同时切换顶部两个下拉框**
  - 没收录的项目直接说「还没收录」，不假装还原

- **从源码画图**
  - 三种输入：GitHub 地址（支持私有仓库）、上传压缩包、本地目录
  - 静态扫描（`source_scan.py`）：目录树、依赖声明、模块 import、类与函数、
    prompt 片段、工具定义线索；Python 走 `ast`，JS/TS 走正则
  - **核心目录优先**排序，避免 `scripts/` 把扫描名额吃满
  - 解压拒绝路径穿越和绝对路径；本地路径拒绝系统目录

- **Harness 框架**（零依赖自实现）
  - 不套任何第三方框架：`agent.py` 就是项目自带的图执行器，读 `agent.json` 跑节点
  - `requirements.txt` 里框架依赖为空，实测 12 个 import 全是标准库 + `runtime_sdk`
  - 用途：表达自研 runtime（如 DeepSeek Harness 这类插件化 agent 容器）的运行时结构

- **画布级 provider**（模型 / 向量 / 数据源）
  - 配置从「用户中心」移到画布，支持多实例，节点参数里可指定跟随默认或选具体实例
  - 密钥只走环境变量注入，不写进项目文件

- **运行附件**
  - 运行面板支持选文件、拖入、粘贴图片，存到项目 `inputs/` 下（单文件 ≤ 20MB）
  - 路径清单拼进 input，并通过 `MINEAGENT_INPUT_FILES` 传给子进程，节点用 `ctx.files` 拿

### 修复

- **`web_search` 节点跑不起来**：生成代码引用 `langchain_community`，但 requirements 里没有，
  一调就 `ModuleNotFoundError`。改用 `ddgs`（DuckDuckGo 对脚本抓 HTML 会返回 202 反爬页，
  零依赖方案拿不到结果），并在缺 ddgs 时给可照做的安装提示
- **非 LangChain 框架缺 `langgraph` 声明**：header 里有 `langgraph.errors` / `langgraph.types`
  的 import，但 requirements 没写，换台机器按声明装会缺
- **约束规则白名单写错 kind**：`MULTI_INPUT_OK` 里写的是 `merge`，真实节点叫 `merger`，
  导致任何用 merger 汇聚的画布都被误报「多入边无法合并」
- **Flowise 指纹用了不存在的 `splitter`**：真实 kind 是 `text_splitter`
- **发布模板时 GitHub 报 400**：不是参数错，是网络把 POST body 截断后 GitHub 回
  `malformed request`。加了重试（3 次指数退避）并在错误信息里带上 URL
- **模型配置被测试污染**：测试脚本直接写生产库的 `app_settings`，把模型配置改成 mock，
  导致助手请求连不上。从备份恢复并加快照，测试不再碰真实配置
- **删除画布不清助手记忆**：只级联删了 `providers` 和 `assistant_chats`，留下孤儿记忆
- **`apply_architecture` 不同步框架/模式**：指纹里的 `framework`/`mode` 是摆设，
  生成画布后顶部下拉框不变

---

## 2026-11-18

这一版的主题是**接入外部新能力**，并把节点从"占位"补成"真能跑"。

### 新增

- **意图识别接入 Jev（TypeSafe System One）**
  - 新增 `ctx.judge(state, questions)`，支持 `choice` / `noul` / `score` 三种题型，
    直接拿到带概率和 confidence 的结构化答案，不再让生成式模型写 JSON 再解析
  - 意图识别节点一次请求同时判断三件事：意图、是否需要调工具、处理量级
  - 支持 `TYPESAFE_API_KEY` / `JEV_ENDPOINT` / `JEV_MODEL`，环境变量和项目 `.env` 都认
  - 没配 key、401、429、451（部分地区不可用）、连不上时自动回退到普通模型，
    结果里用 `engine` 字段标明走的是 `jev` 还是 `llm`

- **LLM Wiki 节点**（`wiki_ingest` / `wiki_query`）
  - 把 RAG 从「查询时做功」改成「入库时理解」：入库就让模型提炼摘要、要点、互链
  - 存储就是项目里的 `wiki/` 目录，一页一个 markdown，可读、可编辑、可 git 管版本
  - 原生模式也用纯 Python 实现，不依赖 `runtime_sdk`

- **Super-agent 双层结构**
  - 新增 `ctx.delegate_many()`：线程池并行派发给多个下级 agent，
    单个 worker 失败不拖垮整体，失败项进 `state["worker_results"]`
  - `supervisor` 从串行改成并行分派，汇总时带上"失败的子任务"
  - 新增 `super_agent` 模式模板（Router → Worker A/B → 汇总）

- **14 张主流编排架构画布**
  - 开源：LangGraph、CrewAI（顺序/层级）、AutoGen、MetaGPT、Dify、n8n、Flowise、Langflow、SmolAgents
  - 闭源：OpenAI Agent Builder、AWS Bedrock Agents、字节 Coze、DeepSeek Super-agent
  - 生成脚本见 `tools/build_framework_blueprints.py`，改一个条目就能扩展

### 改进

- **9 类节点补上真实实现**（原来落到"先用一次模型调用占位"的通用块）
  - `critic` 按标准挑问题并判定通过与否
  - `self_check` 逐条核对输出，返回问题清单
  - `merge` / `join` / `merger` 多路结果保序去重合并
  - `intent_recognizer` 结构化输出意图 + 置信度
  - `doc_loader` 真读 pdf/docx/md/csv，输入不是文件时按正文处理
  - `text_splitter` 按块大小 + 重叠切分
  - `vector_indexer` 写进项目内 SQLite 的 `chunks` 表
  - `hybrid_retriever` 从 `chunks` 表按相关度取回（原来 docs 恒为空）
- `supervisor` 标签补上 Router 字样，并新增 `max_workers` / `timeout` 参数
- 运行日志的时间改用事件产生时刻，不再显示渲染时刻

### 修复

- **多出边丢边**：一个节点连多条出边时按 handle 去重只保留第一条，
  导致下游节点变孤岛、图跑不到终点。改为同端口多条出边全部连上
- **并行写冲突**：并行分支同时写 `data` 触发 LangGraph
  `Can receive only one value per step`，给 `AgentState` 的键加合并 reducer
- **循环无限**：`router` 的 `max_loops` 默认是 0，第一轮就"强制收敛"且方向反了，
  改为默认 4 并支持 `exit_handle` 指定出口
- **框架分发**：`custom` / `dify` / `metagpt` 等无专属 codegen 的框架原来误走 CrewAI 分支，
  生成 `Agent(...)` 但 header 是 LangChain，一跑就 `NameError`
- **连线曲度**：拖动时偏移量加到了端点坐标上，起点终点会跟着跑；改为只偏控制点
- **未注册节点**：Super-agent 画布用的 `merge` 不在节点库里（画布能用、右键搜不到），改用 `merger`
- **依赖缺失**：CrewAI / AutoGen 缺依赖时给出可照做的安装指令，不再甩 traceback
- AutoGen 的 requirements 从 `autogen-agentchat`(0.4 API) 改为 `pyautogen`(0.2)，与生成代码对齐

---

## 2026-11-10

- 采用 Apache-2.0 许可

---

## 2026-11-06

### 新增

- **画布级「服务设置」**：把整张画布编译成可部署的后端服务
  - 生成 `server.py`（`/chat`、`/chat/stream`、`/health`、`/ready`、`/metrics`）
  - 生成 `settings.py`（配置全走环境变量）、`telemetry.py`（结构化日志 + metrics）、
    `checkpoint.py`（会话持久化）
  - 附 `Dockerfile`、`docker-compose.yml`、CI workflow、`tests/`
  - 四组配置：入口、会话、并发、可观测 / 安全

### 文档

- README 补服务设置、节点可靠性、错误出口、生产化文件
- 同步最新界面截图

---

## 2026-11-05

首版功能集中落地的一天。

### 画布与编辑

- MineAgent 可视化 Agent 编排画布（初版）
- 画布背景支持透明 / 底色 / 背景图
- 节点可拖边框缩放
- 画布改动支持撤销 / 重做（按钮 + Ctrl+Z）
- 右键新增节点时按约束自动连线
- 连线不再交叉重叠；自动绕开节点，不压在节点上
- 连线支持点击高亮两端、右键改端点、按住拖动调整走向
- 重写整理布局：按上下游分层，互不重叠、不交叉

### 编排与约束

- 画布编排约束（内置规则库 + 画布级自定义规则）
- Agent 推理模式、多 Agent 组织关系、节点级模型配置
- 输出节点支持 `source` 参数（auto / agent / data）
- 路由节点支持 `question` 参数

### 节点库

- 节点库扩充到 110 个，RAG / 数据 / 文档 / 文本全部细粒度化
- 节点悬停说明改为「概念 / 解释 / 用途 / 编码建议」四段文案
- 新增节点直接用 `agent.py` 原生模板，不再是 `run(ctx)` 那一套

### 代码生成

- 节点代码即 `agent.py` 的代码块，保存增量改代码、运行跑真代码
- 生成的 `agent.py` 改为框架原生代码，取消 `nodes/` 目录
- 节点级模型写进 `agent.py`，所有会调 LLM 的节点都可配
- 生成的项目保证可以单独拿出去跑

### 模型配置

- 配置模型时可以从服务商拉取模型列表
- 模型下拉改用自绘面板，三处配置都加测试连接
- 所有地方的模型默认选择 DeepSeek
- 画布模型弹窗显示「实际生效」配置，避免分不清用了哪份

### 框架与模式

- 框架左边新增「选择模式」下拉，按框架枚举推理模式
- 33 个模式各配一套节点模板，选中直接生成画布

### 界面

- 右列改「AI 助手 / 节点详情」双 tab，节点信息改为悬停浮层
- AI 助手支持历史对话，点「新对话」不再丢掉之前的记录

### 运行与诊断

- 流式运行：模型输出逐 token 回显，执行到哪个节点哪个节点高亮
- 保存时动态扫描节点源码，判断是否用到了大模型
- `critic` 等推理节点右键补上「配置模型」入口

### 社区

- 社区模板分享：把画布提成 GitHub PR，也能加载别人分享的模板
- 用户中心改成下拉（GitHub 账户 / 模型配置 / 公共模板）

---

## 更早

- 项目初始化（Initial commit）
