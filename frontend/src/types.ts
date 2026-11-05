import type { Edge, Node } from '@xyflow/react'

export type NodeParams = Record<string, any>

/** 多 agent 组织关系：全部用节点 id 引用，重命名不受影响 */
export interface AgentOrg {
  superior: string
  subordinates: string[]
  peers: string[]
}

export const EMPTY_ORG: AgentOrg = { superior: '', subordinates: [], peers: [] }

/** 节点级模型配置（api_key 只在写入时出现） */
export interface NodeModelConfig {
  provider?: string
  base_url?: string
  model?: string
  temperature?: number | null
  max_tokens?: number | null
  api_key?: string | null
  api_key_mask?: string
  api_key_env?: string
  has_key?: boolean
  inherit?: boolean
}

/** 这些 kind 属于「自主 agent」，可以选推理模式、配组织关系、单独配模型 */
export const AGENT_KINDS = new Set([
  'agent',
  'worker',
  'supervisor',
  'autogen_assistant',
  'autogen_tool_agent',
  'autogen_group_chat',
  'crewai_agent',
  'crewai_crew',
  'group_chat',
  'debate',
])

export function isAgentKind(kind?: string): boolean {
  return !!kind && AGENT_KINDS.has(kind)
}

/**
 * 这个节点会不会调用大模型。
 * 只要会调用，就允许单独给它配模型 / Key（覆盖画布级和全局配置）。
 */
const LLM_NODE_KINDS = new Set([
  ...AGENT_KINDS,
  'planner', 'observation', 'review_observation', 'reflect', 'critique',
  'formatter', 'format_observations', 'summarize', 'classify', 'extract',
  'translate', 'rewrite', 'judge', 'evaluator', 'writer', 'researcher',
  'llm', 'router', 'condition', 'judge_router', 'intent',
  'rag', 'retriever', 'vector_retriever',
])

export function usesLLM(kind?: string): boolean {
  return !!kind && LLM_NODE_KINDS.has(kind)
}

export type FlowNodeData = {
  kind: string
  label: string
  name: string
  description: string
  code: string
  /** 用户手动改过这段代码：保存时保留他的版本，不重新生成 */
  code_touched?: boolean
  /** 这段代码是从 agent.py 同步回来的 */
  code_generated?: boolean
  /** 保存时扫描源码得出：这个节点会不会调用大模型 */
  uses_llm?: boolean
  /** 零依赖预览用的 run(ctx) 代码（装框架前 runner 执行它） */
  preview_code?: string
  language: string
  params: NodeParams
  status: NodeStatus
  durationMs?: number
  org?: AgentOrg
  model?: NodeModelConfig | null
} & Record<string, unknown>

export type NodeStatus = 'idle' | 'running' | 'done' | 'error' | 'skipped'

export type AgentNode = Node<FlowNodeData, 'agent'>

export type FlowEdge = Edge<
  {
    branch?: string
    /** 拖动连线时产生的人工弯曲偏移，不改 source / target */
    controlOffset?: { x: number; y: number }
  } & Record<string, unknown>
>

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
  rules: CustomRule[]
  /** 画布级默认推理模式，空表示用框架默认 */
  mode?: string
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
  options?: { value: string; label: string }[]
  help?: string
}

export interface NodeDoc {
  concept: string
  explain: string
  usage: string
  tips: string
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
  /** 这个节点会不会调用大模型（由后端按代码判断），会的话允许单独配模型 */
  uses_llm?: boolean
  /** 悬停说明：概念 / 解释 / 用途 / 编码建议 */
  doc?: NodeDoc
  native_code?: string
  default_code?: string
  agent_modes?: string[]
}

export interface AgentModeDef {
  value: string
  label: string
  desc: string
  group?: string
}

/* ---------------- 编排约束 ---------------- */
export interface ConstraintViolation {
  rule: string
  title: string
  level: 'error' | 'warn' | 'info'
  category: string
  message: string
  hint: string
  nodes: string[]
}

export interface ConstraintReport {
  ok: boolean
  errors: ConstraintViolation[]
  warnings: ConstraintViolation[]
  infos: ConstraintViolation[]
  violations: ConstraintViolation[]
  counts: { error: number; warn: number; info: number }
  node_ids: string[]
  checked_rules: number
}

export interface ConstraintRuleDef {
  id: string
  label: string
  level: string
  category: string
  desc: string
}

export interface CustomRuleType {
  type: string
  label: string
  desc: string
}

export type CustomRuleTypeId = 'order' | 'require_kind' | 'forbid_kind' | 'max_count'

export interface CustomRule {
  id: string
  type: CustomRuleTypeId
  label?: string
  level?: 'error' | 'warn'
  node?: string
  anchor?: string
  mode?: 'after' | 'before'
  kind?: string
  count?: number
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
  agent_modes: AgentModeDef[]
  /** 每个框架支持哪些模式（值是 AgentModeDef.value） */
  framework_modes?: Record<string, string[]>
  /** 全量模式清单 */
  all_modes?: AgentModeDef[]
  constraint_rules: ConstraintRuleDef[]
  custom_rule_types: CustomRuleType[]
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

export interface CommunityConfig {
  repo: string
  branch: string
  dir: string
  client_id: string
  client_secret_mask: string
  connected: boolean
  login: string
  configured: boolean
  callback_url: string
}

export interface CommunityTemplate {
  slug: string
  name: string
  description: string
  tags: string[]
  author: string
  framework: string
  node_count: number
  created_at: string
  mode?: string
}

export interface ProjectFileEntry {
  path: string
  size: number
  language: string
}
