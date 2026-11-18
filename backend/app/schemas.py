"""接口出入参模型。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class FlowNodeData(BaseModel):
    """画布节点上所有可编辑的信息。"""

    kind: str = "llm"
    label: str = ""
    name: str = ""
    description: str = ""
    code: str = ""
    # 用户手动改过这段代码：保存时保留他的版本，不重新生成
    code_touched: bool = False
    # 这段代码是从 agent.py 同步回来的
    code_generated: bool = False
    # 保存时扫描源码得出：这个节点会不会调用大模型
    uses_llm: bool = False
    # 零依赖预览用的 run(ctx) 代码
    preview_code: str = ""
    language: str = "python"
    params: Dict[str, Any] = Field(default_factory=dict)
    status: str = "idle"
    # 多 agent 组织关系：{"superior": nodeId, "subordinates": [nodeId], "peers": [nodeId]}
    org: Dict[str, Any] = Field(default_factory=dict)
    # 节点级模型（不含明文 key，key 单独加密存在 agent_models 表）
    model: Optional[Dict[str, Any]] = None


# React Flow 里注册的自定义节点类型；kind 一定放在 data.kind 里
RF_NODE_TYPES = {"agent"}


class FlowNode(BaseModel):
    id: str
    type: str = "agent"
    position: Dict[str, float] = Field(default_factory=lambda: {"x": 0, "y": 0})
    data: FlowNodeData = Field(default_factory=FlowNodeData)
    # 手动拖边框缩放后的尺寸（不填则按内容自适应）
    width: Optional[float] = None
    height: Optional[float] = None


class FlowEdge(BaseModel):
    id: str
    source: str
    target: str
    sourceHandle: Optional[str] = None
    targetHandle: Optional[str] = None
    label: Optional[str] = None
    data: Dict[str, Any] = Field(default_factory=dict)


class CanvasBackground(BaseModel):
    """画布背景。默认纸白，编辑参考线用浅灰点阵。"""

    color: str = "#f8fafc"      # 默认纸白；空字符串 = 透明
    image: str = ""            # 背景图文件名（存 backend/data/backgrounds/）
    image_fit: str = "cover"   # cover / contain / repeat / center
    image_opacity: float = 1.0
    grid: bool = True          # 是否显示点阵网格
    grid_color: str = "#c9d1de"


class Graph(BaseModel):
    nodes: List[FlowNode] = Field(default_factory=list)
    edges: List[FlowEdge] = Field(default_factory=list)
    viewport: Dict[str, float] = Field(default_factory=lambda: {"x": 0, "y": 0, "zoom": 1})
    background: CanvasBackground = Field(default_factory=CanvasBackground)
    # 画布级「服务设置」：入口 / 会话并发 / 可观测 / 安全
    service: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("nodes")
    @classmethod
    def _normalize_node_type(cls, nodes: List[FlowNode]) -> List[FlowNode]:
        """React Flow 只注册了 agent 这一种自定义节点（前端 nodeTypes = {agent}）。

        type 若写成 kind（input / hybrid_retriever 等）会落到 React Flow 的内置兜底节点，
        渲染成没有内容的小白块：节点在、数据也在，只是画不出来。
        这里统一纠正，避免通过 API 或助手 apply_ops 建的画布再踩同一个坑。
        """
        for node in nodes:
            if (node.type or "").strip() not in RF_NODE_TYPES:
                node.type = "agent"
        return nodes


class ModelConfig(BaseModel):
    provider: str = "deepseek"
    base_url: str = ""
    model: str = ""
    temperature: float = 0.3
    max_tokens: int = 2048
    api_key: Optional[str] = None  # 仅在写入时出现；读取时永远是 None
    api_key_mask: str = ""


class CanvasCreate(BaseModel):
    name: Optional[str] = None
    framework: str = "langchain"


class CanvasUpdate(BaseModel):
    name: Optional[str] = None
    framework: Optional[str] = None
    graph: Optional[Graph] = None
    llm_config: Optional[ModelConfig] = None
    background: Optional[CanvasBackground] = None
    rules: Optional[List[Dict[str, Any]]] = None
    mode: Optional[str] = None


class CanvasSummary(BaseModel):
    id: str
    name: str
    slug: str
    framework: str
    node_count: int
    created_at: str
    updated_at: str
    # ---- 远端同步状态（没绑模板时都是空/0）----
    remote_slug: str = ""
    remote_rev: int = 0
    remote_lib: str = ""
    # 库的可读名称：公共模板库 / 私人库 owner/repo
    remote_lib_label: str = ""
    # 远端版本比本地记录的新
    remote_changed: bool = False
    # 本地有未同步的改动
    local_changed: bool = False
    # 远端模板名（列表里显示用）
    remote_name: str = ""


class CanvasDetail(CanvasSummary):
    graph: Graph
    llm_config: ModelConfig
    background: CanvasBackground = Field(default_factory=CanvasBackground)
    rules: List[Dict[str, Any]] = Field(default_factory=list)
    # 画布级默认推理模式（react / plan_execute / cot …），空表示用框架默认
    mode: str = ""


class ConstraintViolation(BaseModel):
    rule: str
    title: str = ""
    level: str = "warn"
    category: str = ""
    message: str = ""
    hint: str = ""
    nodes: List[str] = Field(default_factory=list)


class ConstraintReport(BaseModel):
    ok: bool
    errors: List[ConstraintViolation] = Field(default_factory=list)
    warnings: List[ConstraintViolation] = Field(default_factory=list)
    infos: List[ConstraintViolation] = Field(default_factory=list)
    violations: List[ConstraintViolation] = Field(default_factory=list)
    counts: Dict[str, int] = Field(default_factory=dict)
    node_ids: List[str] = Field(default_factory=list)
    checked_rules: int = 0


class SaveResult(BaseModel):
    ok: bool
    canvas: CanvasDetail
    project_dir: str
    written_files: List[str]
    constraints: Optional[ConstraintReport] = None


class RunRequest(BaseModel):
    input: str = ""
    stream: bool = True
    force: bool = False


class GlobalSettings(BaseModel):
    # 全局「编排用」key：画布上未单独配置模型时回退到这里
    orchestrator_provider: str = "deepseek"
    orchestrator_base_url: str = ""
    orchestrator_model: str = ""
    orchestrator_api_key: Optional[str] = None
    orchestrator_api_key_mask: str = ""
    # 生成项目时连接测试用的默认模型
    install_target: str = ""


class ProjectFile(BaseModel):
    path: str
    content: str
    language: str = "python"


class ProjectTreeEntry(BaseModel):
    path: str
    size: int
    language: str


class AgentNodeModel(BaseModel):
    """单个 agent 节点的模型配置。api_key 只在写入时出现。"""

    provider: str = "deepseek"
    base_url: str = ""
    model: str = ""
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    api_key: Optional[str] = None
    api_key_mask: str = ""
    api_key_env: str = ""
    inherit: bool = True  # True = 跟随画布/全局配置


# --------------------------------------------------------------------------- #
# 向量模型 / 向量库 / 数据源
# --------------------------------------------------------------------------- #
class ProviderIn(BaseModel):
    """新建 / 更新一条 provider 配置。

    config 只放非密文字段；secret 只在写入时出现（密文字段单独加密存储）。
    """

    kind: str = Field(description="embedding | vector | data")
    provider: str = Field(default="", description="catalog 里的厂商 id")
    name: str = ""
    config: Dict[str, Any] = Field(default_factory=dict)
    secret: Optional[Dict[str, Any]] = None
    scope: str = "canvas"          # 现在一律是 canvas；global 只为兼容老数据
    canvas_id: str = ""
    is_default: bool = False


class ProviderOut(BaseModel):
    id: str
    kind: str
    provider: str
    name: str
    label: str = ""
    config: Dict[str, Any] = Field(default_factory=dict)
    secret_mask: Dict[str, str] = Field(default_factory=dict)
    scope: str = "global"
    canvas_id: str = ""
    is_default: bool = False
    status: str = "ready"
    created_at: str = ""
    updated_at: str = ""


class ProviderTestIn(BaseModel):
    """连接测试：可以测未保存的草稿，也可以测已存记录。"""

    kind: str
    provider: str = ""
    config: Dict[str, Any] = Field(default_factory=dict)
    secret: Optional[Dict[str, Any]] = None
    id: Optional[str] = None       # 已存记录时复用其密文与缺省值
    canvas_id: str = ""


# --------------------------------------------------------------------------- #
# AI 助手生成画布的草稿
# --------------------------------------------------------------------------- #
class DraftNode(BaseModel):
    """助手给出的一个节点。key 只在草稿内部用于连线引用。"""

    key: str = ""
    kind: str
    label: str = ""
    name: str = ""
    params: Dict[str, Any] = Field(default_factory=dict)
    code: str = ""


class DraftEdge(BaseModel):
    source: str
    target: str
    branch: str = ""


class CanvasDraft(BaseModel):
    """一张完整画布的草稿：节点 + 连线。"""

    nodes: List[DraftNode] = Field(default_factory=list)
    edges: List[DraftEdge] = Field(default_factory=list)


class ApplyDraftRequest(BaseModel):
    draft: CanvasDraft
    # 是否把助手写的节点代码当作「手改」保留（默认保留）
    keep_code: bool = True


class CanvasOp(BaseModel):
    """一条画布修改操作（增量）。

    op 取值：
      add_node / remove_node / update_node / set_code /
      connect / disconnect / move_node / relayout
    """

    op: str
    # 目标节点：现有节点用 id，新增节点用 key（同一次操作里互相引用）
    id: str = ""
    key: str = ""
    # add_node / update_node 用
    kind: str = ""
    label: str = ""
    name: str = ""
    params: Dict[str, Any] = Field(default_factory=dict)
    # set_code 用
    code: str = ""
    # connect / disconnect 用（可以是 id，也可以是本次 add_node 的 key）
    source: str = ""
    target: str = ""
    branch: str = ""
    # move_node 用
    x: Optional[float] = None
    y: Optional[float] = None


class ApplyOpsRequest(BaseModel):
    operations: List[CanvasOp] = Field(default_factory=list)
    # 应用完是否整体重排一次（位置类需求用）
    relayout: bool = False
