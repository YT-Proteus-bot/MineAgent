import type { Edge, Node } from '@xyflow/react'

export type NodeParams = Record<string, any>

export type FlowNodeData = {
  kind: string
  label: string
  name: string
  description: string
  code: string
  language: string
  params: NodeParams
  status: NodeStatus
  durationMs?: number
} & Record<string, unknown>

export type NodeStatus = 'idle' | 'running' | 'done' | 'error' | 'skipped'

export type AgentNode = Node<FlowNodeData, 'agent'>

export type FlowEdge = Edge<{ branch?: string } & Record<string, unknown>>

export interface GraphPayload {
  nodes: AgentNode[]
  edges: FlowEdge[]
  viewport: { x: number; y: number; zoom: number }
  background?: CanvasBackground
}

export interface ModelConfig {
  provider: string
  base_url: string
  model: string
  temperature: number
  max_tokens: number
  api_key?: string | null
  api_key_mask: string
}

export interface CanvasBackground {
  /** 空字符串表示透明 */
  color: string
  /** 背景图文件名（存在后端的 data/backgrounds 下） */
  image: string
  image_fit: 'cover' | 'contain' | 'repeat' | 'center'
  image_opacity: number
  grid: boolean
  grid_color: string
}

export const DEFAULT_BACKGROUND: CanvasBackground = {
  color: '',
  image: '',
  image_fit: 'cover',
  image_opacity: 1,
  grid: true,
  grid_color: '#1d2740',
}

export interface CanvasSummary {
  id: string
  name: string
  slug: string
  framework: string
  node_count: number
  created_at: string
  updated_at: string
}

export interface CanvasDetail extends CanvasSummary {
  graph: GraphPayload
  llm_config: ModelConfig
  background: CanvasBackground
}

export interface Category {
  id: string
  label: string
  color: string
}

export interface NodeParamDef {
  key: string
  label: string
  default: any
  placeholder: string
}

export interface NodeTypeDef {
  kind: string
  label: string
  category: string
  color: string
  icon: string
  description: string
  outputs: string[]
  params: NodeParamDef[]
  language: string
}

export interface FrameworkDef {
  id: string
  label: string
  runnable: boolean
  badge: string
  color: string
  description: string
  requires: string
}

export interface Meta {
  categories: Category[]
  nodes: NodeTypeDef[]
  frameworks: FrameworkDef[]
  version: string
}

export interface RunEvent {
  event: string
  node?: string
  name?: string
  kind?: string
  label?: string
  level?: string
  message?: string
  output?: any
  text?: string
  status?: string
  duration_ms?: number
  error?: string
  branch?: string
  payload?: any
  [key: string]: any
}

export interface GlobalSettings {
  orchestrator_provider: string
  orchestrator_base_url: string
  orchestrator_model: string
  orchestrator_api_key?: string | null
  orchestrator_api_key_mask: string
}

export interface ProjectFileEntry {
  path: string
  size: number
  language: string
}
