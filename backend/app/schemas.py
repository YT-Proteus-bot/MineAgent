"""接口出入参模型。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class FlowNodeData(BaseModel):
    """画布节点上所有可编辑的信息。"""

    kind: str = "llm"
    label: str = ""
    name: str = ""
    description: str = ""
    code: str = ""
    language: str = "python"
    params: Dict[str, Any] = Field(default_factory=dict)
    status: str = "idle"
    # 多 agent 组织关系：{"superior": nodeId, "subordinates": [nodeId], "peers": [nodeId]}
    org: Dict[str, Any] = Field(default_factory=dict)
    # 节点级模型（不含明文 key，key 单独加密存在 agent_models 表）
    model: Optional[Dict[str, Any]] = None


class FlowNode(BaseModel):
    id: str
    type: str = "agent"
    position: Dict[str, float] = Field(default_factory=lambda: {"x": 0, "y": 0})
    data: FlowNodeData = Field(default_factory=FlowNodeData)


class FlowEdge(BaseModel):
    id: str
    source: str
    target: str
    sourceHandle: Optional[str] = None
    targetHandle: Optional[str] = None
    label: Optional[str] = None
    data: Dict[str, Any] = Field(default_factory=dict)


class CanvasBackground(BaseModel):
    """画布背景。默认全透明，只保留很淡的点阵网格作为编辑参考。"""

    color: str = ""            # 空字符串 = 透明
    image: str = ""            # 背景图文件名（存 backend/data/backgrounds/）
    image_fit: str = "cover"   # cover / contain / repeat / center
    image_opacity: float = 1.0
    grid: bool = True          # 是否显示点阵网格
    grid_color: str = "#1d2740"


class Graph(BaseModel):
    nodes: List[FlowNode] = Field(default_factory=list)
    edges: List[FlowEdge] = Field(default_factory=list)
    viewport: Dict[str, float] = Field(default_factory=lambda: {"x": 0, "y": 0, "zoom": 1})
    background: CanvasBackground = Field(default_factory=CanvasBackground)


class ModelConfig(BaseModel):
    provider: str = "openai"
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


class CanvasSummary(BaseModel):
    id: str
    name: str
    slug: str
    framework: str
    node_count: int
    created_at: str
    updated_at: str


class CanvasDetail(CanvasSummary):
    graph: Graph
    llm_config: ModelConfig
    background: CanvasBackground = Field(default_factory=CanvasBackground)


class SaveResult(BaseModel):
    ok: bool
    canvas: CanvasDetail
    project_dir: str
    written_files: List[str]


class RunRequest(BaseModel):
    input: str = ""
    stream: bool = True


class GlobalSettings(BaseModel):
    # 全局「编排用」key：画布上未单独配置模型时回退到这里
    orchestrator_provider: str = "openai"
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

    provider: str = "openai"
    base_url: str = ""
    model: str = ""
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    api_key: Optional[str] = None
    api_key_mask: str = ""
    api_key_env: str = ""
    inherit: bool = True  # True = 跟随画布/全局配置
