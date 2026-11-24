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
  service?: ServiceConfig
}

/** 画布级「服务设置」：入口 / 会话与并发 / 可观测 / 安全 / 数据 / 评测 */
export interface ServiceConfig {
  entry: { mode: string; path: string; auth: string; cors: string }
  session: { store: string; max_turns: number; ttl_minutes: number }
  runtime: { max_concurrency: number; queue_limit: number; run_timeout_s: number; resume: boolean }
  observability: {
    log_level: string
    json_logs: boolean
    metrics: boolean
    trace_sample: number
    budget_usd: number
  }
  security: { sandbox: string; guardrail: string; pii: boolean; audit: boolean }
  data: {
    enabled: boolean
    kind: string
    base_url: string
    auth: string
    secret_ref: string
    datasets: { logical: string; physical: string; mode: string }[]
    timeout_s: number
    pii_fields: string[]
  }
  eval: {
    enabled: boolean
    kind: string
    base_url: string
    auth: string
    secret_ref: string
    project: string
    evalsets: { logical: string; remote: string }[]
    report_on_run: boolean
    pass_rate: number
    latency_p95_ms: number
  }
}

export const DEFAULT_SERVICE: ServiceConfig = {
  entry: { mode: 'both', path: '/chat', auth: 'none', cors: '*' },
  session: { store: 'sqlite', max_turns: 20, ttl_minutes: 1440 },
  runtime: { max_concurrency: 4, queue_limit: 100, run_timeout_s: 600, resume: false },
  observability: { log_level: 'info', json_logs: true, metrics: true, trace_sample: 1, budget_usd: 0 },
  security: { sandbox: 'restricted', guardrail: 'log', pii: false, audit: true },
  data: {
    enabled: false,
    kind: 'http',
    base_url: '',
    auth: 'bearer',
    secret_ref: 'MINEAGENT_DATA_TOKEN',
    datasets: [],
    timeout_s: 30,
    pii_fields: [],
  },
  eval: {
    enabled: false,
    kind: 'http',
    base_url: '',
    auth: 'bearer',
    secret_ref: 'MINEAGENT_EVAL_TOKEN',
    project: '',
    evalsets: [],
    report_on_run: true,
    pass_rate: 0.8,
    latency_p95_ms: 8000,
  },
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
  color: '#f8fafc',
  image: '',
  image_fit: 'cover',
  image_opacity: 1,
  grid: true,
  grid_color: '#c9d1de',
}

export interface CanvasSummary {
  id: string
  name: string
  slug: string
  framework: string
  node_count: number
  created_at: string
  updated_at: string
  /** 绑定的远端模板（没同步过就是空） */
  remote_slug?: string
  remote_rev?: number
  /** 来源库：public 或 private:owner/repo */
  remote_lib?: string
  /** 库的可读名称：公共模板库 / 私人库 owner/repo */
  remote_lib_label?: string
  /** 远端模板名（下拉里括号显示） */
  remote_name?: string
  /** 远端有比本地记录更新的版本 */
  remote_changed?: boolean
  /** 本地有没同步出去的改动 */
  local_changed?: boolean
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
  /** 这个参数要选画布里的哪类实例（embedding / rerank / vector / data） */
  source?: ProviderKind
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
  /** 内置工具清单：tool 节点的下拉与专属参数 */
  tool_presets?: ToolPreset[]
  version: string
}

export interface ToolPreset {
  id: string
  label: string
  description: string
  /** 一句话说清这段代码干了什么，套用后会写进节点说明 */
  summary?: string
  args: string
  params: { key: string; label: string; default: any }[]
}

/** 用户中心配置的模板库（公共 / 私人，可有多个） */
export interface TemplateLib {
  id: string
  name: string
  kind: 'public' | 'private'
  repo: string
  branch: string
  dir: string
  /** 保存时用用户 token 校验出的仓库可见性 */
  visibility?: 'public' | 'private'
}

/** 后台上传任务：点上传后立即关闭弹窗，任务在后台跑 */
export interface UploadJob {
  id: string
  canvasId: string
  name: string
  status: 'running' | 'ok' | 'error'
  prUrl: string
  error?: string
}

export interface RunEvent {
  event: string
  /** 事件产生时间（后端发出时打的），日志前面的时间显示的就是它 */
  at?: string
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

/* ---------------- 向量模型 / 重排模型 / 向量库 / 数据源 ---------------- */
export type ProviderKind = 'embedding' | 'rerank' | 'vector' | 'data'

export interface ProviderField {
  key: string
  label: string
  required: boolean
  /** 密钥类字段：单独加密存储，接口只回显掩码 */
  secret: boolean
  default: any
  placeholder: string
  kind: 'text' | 'password' | 'number' | 'select' | 'textarea'
  help: string
  options?: string[]
}

export interface ProviderModelDef {
  id: string
  dim: number
}

export interface CatalogItem {
  id: string
  label: string
  group: string
  protocol: string
  /** ready = 已实现；planned = 已列入、适配器后续补齐 */
  status: 'ready' | 'planned'
  pip: string
  fields: ProviderField[]
  help: string
  base_url: string
  key_required: boolean
  models: ProviderModelDef[]
}

export interface CatalogKind {
  id: ProviderKind
  label: string
  desc: string
  items: CatalogItem[]
}

export interface ProviderCatalog {
  groups: Record<string, string>
  kinds: CatalogKind[]
}

export interface ProviderRecord {
  id: string
  kind: ProviderKind
  provider: string
  name: string
  label: string
  config: Record<string, any>
  /** 密钥字段的掩码，形如 sk-****abcd */
  secret_mask: Record<string, string>
  scope: string
  canvas_id: string
  is_default: boolean
  status: string
  created_at: string
  updated_at: string
}

export interface ProviderTestResult {
  ok: boolean
  message: string
  hint?: string
  stage?: string
  protocol?: string
  dim?: number
  latency_ms?: number
  tables?: string[]
  error?: string
}
