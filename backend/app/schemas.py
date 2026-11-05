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


class Graph(BaseModel):
    nodes: List[FlowNode] = Field(default_factory=list)
    edges: List[FlowEdge] = Field(default_factory=list)
    viewport: Dict[str, float] = Field(default_factory=lambda: {"x": 0, "y": 0, "zoom": 1})


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
