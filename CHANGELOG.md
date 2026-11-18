# 更新记录

只记"做了什么、修了什么"，产品介绍和使用方法看 [README.md](README.md)。
日期为提交日期，同一日期内的条目按实现顺序排列。

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
