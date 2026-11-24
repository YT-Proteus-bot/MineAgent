import type {
  CanvasBackground,
  CanvasDetail,
  CanvasSummary,
  CommunityConfig,
  CommunityTemplate,
  ConstraintReport,
  CustomRule,
  GlobalSettings,
  GraphPayload,
  Meta,
  ModelConfig,
  ProjectFileEntry,
  ProviderCatalog,
  ProviderKind,
  ProviderRecord,
  ProviderTestResult,
  RunEvent,
  TemplateLib,
} from './types'

const BASE = ''

/** 带状态码和结构化 detail 的错误：冲突（409）要靠它区分是哪种冲突。 */
export class ApiError extends Error {
  status: number
  detail: any

  constructor(status: number, detail: any, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(BASE + path, {
    ...init,
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
      ...(init?.headers || {}),
    },
  })
  if (!resp.ok) {
    let detail: any = `${resp.status} ${resp.statusText}`
    try {
      const body = await resp.json()
      detail = body.detail ?? body
    } catch {
      /* ignore */
    }
    const message = typeof detail === 'string' ? detail : detail?.message || JSON.stringify(detail)
    throw new ApiError(resp.status, detail, message)
  }
  if (resp.status === 204) return undefined as T
  return (await resp.json()) as T
}

export const api = {
  meta: () => request<Meta>('/api/meta'),

  listCanvases: () => request<CanvasSummary[]>('/api/canvases'),
  createCanvas: (name: string | null, framework: string) =>
    request<CanvasDetail>('/api/canvases', {
      method: 'POST',
      body: JSON.stringify({ name, framework }),
    }),
  getCanvas: (id: string) => request<CanvasDetail>(`/api/canvases/${id}`),
  updateCanvas: (id: string, patch: Record<string, any>) =>
    request<CanvasDetail>(`/api/canvases/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),
  saveCanvas: (id: string, graph: GraphPayload) =>
    request<{
      ok: boolean
      canvas: CanvasDetail
      project_dir: string
      written_files: string[]
      constraints: ConstraintReport | null
    }>(`/api/canvases/${id}/save`, { method: 'POST', body: JSON.stringify(graph) }),
  validateCanvas: (id: string, graph?: GraphPayload) =>
    request<ConstraintReport>(`/api/canvases/${id}/validate`, {
      method: 'POST',
      body: JSON.stringify(graph || {}),
    }),
  /** 把 AI 助手生成的画布草稿替换到当前画布（可顺带切换框架和模式） */
  applyDraft: (id: string, draft: Record<string, any>, framework?: string, mode?: string) =>
    request<{ ok: boolean; canvas: CanvasDetail; constraints: ConstraintReport }>(
      `/api/canvases/${id}/apply-draft`,
      {
        method: 'POST',
        body: JSON.stringify({
          draft,
          framework: framework || '',
          mode: mode || '',
        }),
      },
    ),
  /** 增量修改画布：增删节点 / 改参数与代码 / 连线 / 挪位置 */
  applyOps: (id: string, operations: Record<string, any>[], relayout = false) =>
    request<{
      ok: boolean
      applied: number
      errors: string[]
      canvas: CanvasDetail
      constraints: ConstraintReport
    }>(`/api/canvases/${id}/apply-ops`, {
      method: 'POST',
      body: JSON.stringify({ operations, relayout }),
    }),
  setRules: (id: string, rules: CustomRule[]) =>
    request<{ ok: boolean; rules: CustomRule[] }>(`/api/canvases/${id}/rules`, {
      method: 'PUT',
      body: JSON.stringify(rules),
    }),
  deleteCanvas: (id: string) =>
    request<{ ok: boolean }>(`/api/canvases/${id}`, { method: 'DELETE' }),
  setCanvasModel: (id: string, cfg: ModelConfig) =>
    request<CanvasDetail>(`/api/canvases/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({ llm_config: cfg }),
    }),
  setBackground: (id: string, bg: CanvasBackground) =>
    request<CanvasDetail>(`/api/canvases/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({ background: bg }),
    }),
  uploadBackground: async (id: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    const resp = await fetch(`/api/canvases/${id}/background-image`, {
      method: 'POST',
      body: form,
    })
    if (!resp.ok) {
      let detail = `${resp.status} ${resp.statusText}`
      try {
        const body = await resp.json()
        detail = body.detail || detail
      } catch {
        /* ignore */
      }
      throw new Error(detail)
    }
    return (await resp.json()) as {
      ok: boolean
      filename: string
      url: string
      background: CanvasBackground
      size: number
    }
  },
  deleteBackground: (id: string) =>
    request<{ ok: boolean; background: CanvasBackground }>(
      `/api/canvases/${id}/background-image`,
      { method: 'DELETE' },
    ),
  setNodeModel: (id: string, nodeId: string, cfg: Record<string, any>) =>
    request<Record<string, any>>(`/api/canvases/${id}/nodes/${nodeId}/model`, {
      method: 'PUT',
      body: JSON.stringify(cfg),
    }),
  clearNodeModel: (id: string, nodeId: string) =>
    request<{ ok: boolean }>(`/api/canvases/${id}/nodes/${nodeId}/model`, { method: 'DELETE' }),
  applyToolPreset: (canvasId: string, nodeId: string, preset: string) =>
    request<{
      ok: boolean
      preset: string
      label: string
      code: string
      preview_code: string
      params: Record<string, any>
    }>(`/api/canvases/${canvasId}/nodes/${nodeId}/apply-tool`, {
      method: 'POST',
      body: JSON.stringify({ preset }),
    }),
  describeNode: (canvasId: string, nodeId: string) =>
    request<{ ok: boolean; description: string }>(
      `/api/canvases/${canvasId}/nodes/${nodeId}/describe`,
      { method: 'POST' },
    ),

  env: (id: string) => request<Record<string, any>>(`/api/canvases/${id}/env`),
  listFiles: (id: string) =>
    request<{ root: string; files: ProjectFileEntry[] }>(`/api/canvases/${id}/files`),
  readFile: (id: string, path: string) =>
    request<{ path: string; content: string; language: string }>(
      `/api/canvases/${id}/file?path=${encodeURIComponent(path)}`,
    ),
  writeFile: (id: string, path: string, content: string) =>
    request<{ ok: boolean }>(`/api/canvases/${id}/file`, {
      method: 'PUT',
      body: JSON.stringify({ path, content, language: 'text' }),
    }),
  openFolder: (id: string) =>
    request<{ ok: boolean; path: string }>(`/api/canvases/${id}/open-folder`, { method: 'POST' }),

  getSettings: () => request<GlobalSettings>('/api/settings'),
  putSettings: (s: Partial<GlobalSettings>) =>
    request<GlobalSettings>('/api/settings', { method: 'PUT', body: JSON.stringify(s) }),
  testModel: (payload: { api_key?: string; base_url?: string; model?: string }) =>
    request<{ ok: boolean; message: string }>('/api/settings/test', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  listModels: (payload: { base_url?: string; api_key?: string }) =>
    request<{ ok: boolean; models: string[]; count?: number; message: string }>(
      '/api/settings/models',
      { method: 'POST', body: JSON.stringify(payload) },
    ),

  // ---- 向量模型 / 向量库 / 数据源 ----
  providerCatalog: () => request<ProviderCatalog>('/api/providers/catalog'),
  listProviders: (params?: { kind?: string; canvas_id?: string }) => {
    const q = new URLSearchParams()
    if (params?.kind) q.set('kind', params.kind)
    if (params?.canvas_id) q.set('canvas_id', params.canvas_id)
    const suffix = q.toString() ? `?${q.toString()}` : ''
    return request<ProviderRecord[]>(`/api/providers${suffix}`)
  },
  createProvider: (payload: Partial<ProviderRecord> & { secret?: Record<string, string> }) =>
    request<ProviderRecord>('/api/providers', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  updateProvider: (
    id: string,
    payload: Partial<ProviderRecord> & { secret?: Record<string, string> },
  ) =>
    request<ProviderRecord>(`/api/providers/${id}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),
  setProviderDefault: (id: string) =>
    request<ProviderRecord>(`/api/providers/${id}/default`, { method: 'POST' }),
  deleteProvider: (id: string) =>
    request<{ ok: boolean }>(`/api/providers/${id}`, { method: 'DELETE' }),
  testProvider: (payload: {
    kind: string
    provider: string
    config?: Record<string, any>
    secret?: Record<string, string>
    id?: string
  }) =>
    request<ProviderTestResult>('/api/providers/test', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  /** 按字段深合并画布的服务设置 */
  updateService: (id: string, patch: Record<string, any>) =>
    request<{ ok: boolean; canvas: CanvasDetail; service: Record<string, any> }>(
      `/api/canvases/${id}/service`,
      { method: 'PATCH', body: JSON.stringify(patch) },
    ),

  // ---- 运行附件（文件 / 图片） ----
  listInputs: (id: string) =>
    request<{ files: { name: string; path: string; size: number }[] }>(
      `/api/canvases/${id}/inputs`,
    ),
  uploadInput: async (id: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    const resp = await fetch(`/api/canvases/${id}/inputs`, {
      method: 'POST',
      body: form,
    })
    if (!resp.ok) {
      let detail = `${resp.status} ${resp.statusText}`
      try {
        const body = await resp.json()
        detail = body.detail || detail
      } catch {
        /* ignore */
      }
      throw new Error(detail)
    }
    return (await resp.json()) as {
      ok: boolean
      file: { name: string; path: string; size: number }
    }
  },
  deleteInput: (id: string, path: string) =>
    request<{ ok: boolean }>(
      `/api/canvases/${id}/inputs?path=${encodeURIComponent(path)}`,
      { method: 'DELETE' },
    ),

  // ---- 评测中台 ----
  listDatasets: () => request<{ items: any[] }>('/api/eval/datasets'),
  createDataset: (payload: Record<string, any>) =>
    request<{ ok: boolean; dataset: any }>('/api/eval/datasets', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  getDataset: (id: string) =>
    request<{ dataset: any }>(`/api/eval/datasets/${id}`),
  deleteDataset: (id: string) =>
    request<{ ok: boolean }>(`/api/eval/datasets/${id}`, { method: 'DELETE' }),
  listEvalRuns: (limit = 30) =>
    request<{ items: any[] }>(`/api/eval/runs?limit=${limit}`),
  createEvalRun: (payload: Record<string, any>) =>
    request<{ ok: boolean; run: any }>('/api/eval/runs', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  getEvalRun: (id: string) => request<{ run: any }>(`/api/eval/runs/${id}`),
  compareEvalRun: (id: string, base: string) =>
    request<{ ok: boolean; compare: any }>(
      `/api/eval/runs/${id}/compare?base=${encodeURIComponent(base)}`,
    ),
  evalTrend: (params: { canvas_id?: string; dataset_id?: string; limit?: number } = {}) => {
    const q = new URLSearchParams()
    if (params.canvas_id) q.set('canvas_id', params.canvas_id)
    if (params.dataset_id) q.set('dataset_id', params.dataset_id)
    if (params.limit) q.set('limit', String(params.limit))
    const suffix = q.toString() ? `?${q.toString()}` : ''
    return request<{ items: any[] }>(`/api/eval/trend${suffix}`)
  },
  deleteEvalRun: (id: string) =>
    request<{ ok: boolean }>(`/api/eval/runs/${id}`, { method: 'DELETE' }),
  setEvalVerdict: (resultId: string, verdict: string, note = '') =>
    request<{ ok: boolean }>(`/api/eval/results/${resultId}`, {
      method: 'PATCH',
      body: JSON.stringify({ verdict, note }),
    }),

  // ---- 知识库（全局） ----
  listKnowledge: () => request<{ items: any[] }>('/api/knowledge'),
  createKnowledge: (payload: Record<string, any>) =>
    request<{ ok: boolean; kb: any }>('/api/knowledge', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  getKnowledge: (id: string) =>
    request<{ kb: any }>(`/api/knowledge/${id}`),
  updateKnowledge: (id: string, payload: Record<string, any>) =>
    request<{ ok: boolean; kb: any }>(`/api/knowledge/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),
  deleteKnowledge: (id: string) =>
    request<{ ok: boolean }>(`/api/knowledge/${id}`, { method: 'DELETE' }),
  uploadKbFile: async (id: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    const resp = await fetch(`/api/knowledge/${id}/files`, {
      method: 'POST',
      body: form,
    })
    if (!resp.ok) {
      let detail = `${resp.status} ${resp.statusText}`
      try {
        const body = await resp.json()
        detail = body.detail || detail
      } catch {
        /* ignore */
      }
      throw new Error(detail)
    }
    return (await resp.json()) as { ok: boolean; file: any; files: any[] }
  },
  deleteKbFile: (id: string, name: string) =>
    request<{ ok: boolean; files: any[] }>(
      `/api/knowledge/${id}/files?name=${encodeURIComponent(name)}`,
      { method: 'DELETE' },
    ),
  buildKnowledge: (id: string) =>
    request<{ ok: boolean; files: number; chunks: number; dim: number }>(
      `/api/knowledge/${id}/build`,
      { method: 'POST' },
    ),
  searchKnowledge: (id: string, q: string, topK = 5) =>
    request<{ ok: boolean; hits: any[] }>(
      `/api/knowledge/${id}/search?q=${encodeURIComponent(q)}&top_k=${topK}`,
    ),

  // ---- 源码包（从源码还原架构） ----
  listSources: () =>
    request<{ sources: any[] }>('/api/sources'),
  uploadSource: async (file: File) => {
    const form = new FormData()
    form.append('file', file)
    const resp = await fetch('/api/sources/upload', { method: 'POST', body: form })
    if (!resp.ok) {
      let detail = `${resp.status} ${resp.statusText}`
      try {
        const body = await resp.json()
        detail = body.detail || detail
      } catch {
        /* ignore */
      }
      throw new Error(detail)
    }
    return (await resp.json()) as { ok: boolean; source_id: string; source: any }
  },
  scanSource: (id: string) =>
    request<Record<string, any>>(`/api/sources/${id}/scan`),
  deleteSource: (id: string) =>
    request<{ ok: boolean }>(`/api/sources/${id}`, { method: 'DELETE' }),

  // ---- AI 助手历史对话 ----
  /** 传 canvasId 就只取这张画布的对话 */
  listChats: (canvasId?: string) =>
    request<
      { id: string; title: string; message_count: number; updated_at: string }[]
    >(
      `/api/assistant/chats${
        canvasId ? `?canvas_id=${encodeURIComponent(canvasId)}` : ''
      }`,
    ),
  getChat: (id: string) =>
    request<{ id: string; title: string; messages: ChatMsg[]; updated_at: string }>(
      `/api/assistant/chats/${id}`,
    ),
  saveChat: (payload: {
    messages: ChatMsg[]
    chat_id?: string
    title?: string
    canvas_id?: string
    summary?: string
  }) =>
    request<{ ok: boolean; id: string; title?: string }>('/api/assistant/chats', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  deleteChat: (id: string) =>
    request<{ ok: boolean }>(`/api/assistant/chats/${id}`, { method: 'DELETE' }),

  /** 把较早的对话压成摘要（上下文压缩） */
  compressChat: (messages: ChatMsg[], canvasId: string) =>
    request<{ ok: boolean; summary: string; kept: number; dropped: number }>(
      '/api/assistant/compress',
      { method: 'POST', body: JSON.stringify({ messages, canvas_id: canvasId }) },
    ),

  // ---- 助手长期记忆（按画布） ----
  listMemories: (canvasId: string) =>
    request<{ ok: boolean; memories: any[] }>(
      `/api/assistant/memories?canvas_id=${encodeURIComponent(canvasId)}`,
    ),
  addMemory: (canvasId: string, content: string, kind = 'note') =>
    request<{ ok: boolean; id: string }>('/api/assistant/memories', {
      method: 'POST',
      body: JSON.stringify({ canvas_id: canvasId, content, kind }),
    }),
  deleteMemory: (id: string) =>
    request<{ ok: boolean }>(`/api/assistant/memories/${id}`, { method: 'DELETE' }),
  clearMemories: (canvasId: string) =>
    request<{ ok: boolean; removed: number }>(
      `/api/assistant/memories?canvas_id=${encodeURIComponent(canvasId)}`,
      { method: 'DELETE' },
    ),

  // ---- 模式模板 ----
  modeTemplates: () =>
    request<Record<string, { mode: string; name: string; summary: string; node_count: number }>>(
      '/api/meta/modes',
    ),
  modeTemplate: (mode: string, framework: string) =>
    request<{
      nodes: any[]
      edges: any[]
      viewport: any
      name: string
      summary: string
      mode: string
    }>(`/api/meta/modes/${mode}?framework=${encodeURIComponent(framework)}`),

  // ---- 社区模板 ----
  communityConfig: () => request<CommunityConfig>('/api/community/config'),
  saveCommunityConfig: (payload: Record<string, any>) =>
    request<{ ok: boolean }>('/api/community/config', {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),
  communityAuthUrl: () =>
    request<{ url: string; state: string }>('/api/community/auth/url'),
  communityDisconnect: () =>
    request<{ ok: boolean }>('/api/community/disconnect', { method: 'POST' }),
  publishTemplate: (
    payload: {
      canvas_id: string
      name: string
      description: string
      tags: string[]
      author: string
      target?: 'public' | 'private'
      /** 目标模板库（用户中心配置的库 id） */
      lib_id?: string
      /** 上次同步到的远端版本，用于冲突检测 */
      base_rev?: number
      remote_slug?: string
      /** 用户在冲突对话框里选了「仍然覆盖」 */
      force?: boolean
    },
    signal?: AbortSignal,
  ) =>
    request<{
      ok: boolean
      target?: string
      pr_url?: string
      pr_number?: number
      commit_url?: string
      branch: string
      slug: string
      files: string[]
    }>('/api/community/publish', {
      method: 'POST',
      body: JSON.stringify(payload),
      signal,
    }),
  privateConfig: (canvasId: string) =>
    request<{ ok: boolean; repo: string; branch: string; dir: string }>(
      `/api/community/private-config?canvas_id=${encodeURIComponent(canvasId)}`,
    ),
  savePrivateConfig: (payload: {
    canvas_id: string
    repo: string
    branch: string
    dir: string
  }) =>
    request<{ ok: boolean; repo: string; branch: string; dir: string }>(
      '/api/community/private-config',
      { method: 'PUT', body: JSON.stringify(payload) },
    ),
  privateTemplates: (canvasId: string) =>
    request<{ ok: boolean; templates: CommunityTemplate[] }>(
      `/api/community/private-templates?canvas_id=${encodeURIComponent(canvasId)}`,
    ),
  privateLoad: (payload: { canvas_id: string; slug: string }) =>
    request<{ ok: boolean; canvas: CanvasDetail }>('/api/community/private-load', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  communityTemplates: () =>
    request<{ ok: boolean; configured: boolean; templates: CommunityTemplate[] }>(
      '/api/community/templates',
    ),
  communityLibs: () =>
    request<{ ok: boolean; libs: TemplateLib[] }>('/api/community/libs'),
  saveCommunityLibs: (libs: TemplateLib[]) =>
    request<{ ok: boolean; libs: TemplateLib[] }>('/api/community/libs', {
      method: 'PUT',
      body: JSON.stringify({ libs }),
    }),
  canvasLib: (canvasId: string) =>
    request<{ ok: boolean; lib_id: string }>(
      `/api/community/canvas-lib?canvas_id=${encodeURIComponent(canvasId)}`,
    ),
  saveCanvasLib: (canvasId: string, libId: string) =>
    request<{ ok: boolean; lib_id: string }>('/api/community/canvas-lib', {
      method: 'PUT',
      body: JSON.stringify({ canvas_id: canvasId, lib_id: libId }),
    }),
  libCount: (libId: string) =>
    request<{ ok: boolean; count: number }>(
      `/api/community/lib-count?lib_id=${encodeURIComponent(libId)}`,
    ),
  libTemplates: (libId: string, refresh = false) =>
    request<{ ok: boolean; lib: TemplateLib; templates: CommunityTemplate[] }>(
      `/api/community/lib-templates?lib_id=${encodeURIComponent(libId)}${refresh ? '&refresh=1' : ''}`,
    ),
  libLoad: (libId: string, slug: string) =>
    request<{ ok: boolean; canvas: CanvasDetail }>('/api/community/lib-load', {
      method: 'POST',
      body: JSON.stringify({ lib_id: libId, slug }),
    }),
  communityPending: () =>
    request<{
      ok: boolean
      pending: { name: string; canvas_id?: string; pr_url: string; pr_number: number }[]
    }>('/api/community/pending'),
  communityCanvasStatus: () =>
    request<{
      ok: boolean
      templates: {
        slug?: string
        name: string
        canvas_id?: string
        canvas_updated_at?: string
        graph_hash?: string
        node_count?: number
        created_at?: string
      }[]
      prs: {
        name: string
        canvas_id?: string
        state: 'open' | 'merged' | 'closed'
        pr_number: number
        pr_url: string
        created_at?: string
      }[]
    }>('/api/community/canvas-status'),
  loadCommunityTemplate: (
    slug: string,
    options?: { mode?: 'new' | 'update'; canvasId?: string; force?: boolean },
  ) =>
    request<{ ok: boolean; canvas: CanvasDetail; mode?: string; rev?: number }>(
      '/api/community/load',
      {
        method: 'POST',
        body: JSON.stringify({
          slug,
          mode: options?.mode || 'new',
          canvas_id: options?.canvasId || '',
          force: !!options?.force,
        }),
      },
    ),
  communitySyncOverview: () =>
    request<{
      ok: boolean
      items: {
        canvas_id: string
        canvas_name: string
        remote_slug: string
        remote_lib: string
        remote_lib_label: string
        remote_name: string
        local_rev: number
        remote_rev: number
        remote_changed: boolean
        local_changed: boolean
        remote_updated_at: string
      }[]
    }>('/api/community/sync-overview'),
  communitySyncStatus: (canvasId: string) =>
    request<{
      ok: boolean
      linked: boolean
      remote_slug?: string
      local_rev?: number
      remote_rev?: number
      local_changed?: boolean
      remote_changed?: boolean
      local_hash?: string
      remote_hash?: string
      remote_updated_at?: string
      error?: string
    }>(`/api/community/sync-status/${encodeURIComponent(canvasId)}`),

  assistantStatus: () =>
    request<{ ready: boolean; model: string; base_url: string; hint: string }>(
      '/api/assistant/status',
    ),
}

export interface ChatMsg {
  role: 'user' | 'assistant'
  content: string
}

/** 内置助手（Agent 形态）：流式对话 + 工具事件 + 待确认动作 */
export type AssistantEvent = {
  event: string
  text?: string
  message?: string
  tool?: string
  args?: Record<string, any>
  summary?: string
  payload?: Record<string, any>
  [key: string]: any
}

export async function assistantChat(
  opts: {
    messages: ChatMsg[]
    context: Record<string, any>
    canvasId?: string
    summary?: string
    onToken: (text: string) => void
    onError: (message: string) => void
    onDone: () => void
    onEvent?: (evt: AssistantEvent) => void
  },
  signal?: AbortSignal,
): Promise<void> {
  const { onToken, onError, onDone, onEvent } = opts
  let resp: Response
  try {
    resp = await fetch('/api/assistant/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json; charset=utf-8' },
      body: JSON.stringify({
        messages: opts.messages,
        context: opts.context,
        canvas_id: opts.canvasId || '',
        summary: opts.summary || '',
      }),
      signal,
    })
  } catch (err: any) {
    if (err?.name !== 'AbortError') onError(String(err?.message || err))
    return
  }
  if (!resp.ok || !resp.body) {
    let detail = `助手接口返回 ${resp.status}`
    try {
      const body = await resp.json()
      detail = typeof body.detail === 'string' ? body.detail : detail
    } catch {
      /* ignore */
    }
    onError(detail)
    return
  }
  const reader = resp.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  while (true) {
    let chunk: ReadableStreamReadResult<Uint8Array>
    try {
      chunk = await reader.read()
    } catch (err: any) {
      if (err?.name !== 'AbortError') onError(String(err?.message || err))
      break
    }
    if (chunk.done) break
    buffer += decoder.decode(chunk.value, { stream: true })
    const parts = buffer.split('\n\n')
    buffer = parts.pop() || ''
    for (const part of parts) {
      const line = part.split('\n').find((l) => l.startsWith('data:'))
      if (!line) continue
      try {
        const evt = JSON.parse(line.slice(5).trim()) as AssistantEvent
        onEvent?.(evt)
        if (evt.event === 'token') onToken(evt.text || '')
        else if (evt.event === 'error') onError(evt.message || '')
        else if (evt.event === 'done') onDone()
      } catch {
        /* 忽略半行 */
      }
    }
  }
}

export interface RunHandle {
  abort: () => void
}

export async function runCanvas(
  canvasId: string,
  input: string,
  onEvent: (evt: RunEvent) => void,
  onError: (message: string) => void,
  onConstraintBlocked?: (detail: { message: string; violations: any[] }) => void,
  files: string[] = [],
): Promise<RunHandle> {
  const controller = new AbortController()
  const run = async () => {
    let resp: Response
    try {
      resp = await fetch(`/api/canvases/${canvasId}/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json; charset=utf-8' },
        body: JSON.stringify({ input, files }),
        signal: controller.signal,
      })
    } catch (err: any) {
      if (err?.name !== 'AbortError') onError(String(err?.message || err))
      return
    }
    if (resp.status === 409) {
      const body = await resp.json().catch(() => ({}) as any)
      const detail = body?.detail || {}
      onConstraintBlocked?.({
        message: detail.message || '画布不满足约束，已阻止运行',
        violations: detail.violations || [],
      })
      return
    }
    if (!resp.ok || !resp.body) {
      onError(`运行接口返回 ${resp.status}`)
      return
    }
    const reader = resp.body.getReader()
    const decoder = new TextDecoder('utf-8')
    let buffer = ''
    while (true) {
      let chunk: ReadableStreamReadResult<Uint8Array>
      try {
        chunk = await reader.read()
      } catch (err: any) {
        if (err?.name !== 'AbortError') onError(String(err?.message || err))
        break
      }
      if (chunk.done) break
      buffer += decoder.decode(chunk.value, { stream: true })
      const parts = buffer.split('\n\n')
      buffer = parts.pop() || ''
      for (const part of parts) {
        const line = part.split('\n').find((l) => l.startsWith('data:'))
        if (!line) continue
        try {
          onEvent(JSON.parse(line.slice(5).trim()) as RunEvent)
        } catch {
          /* 忽略半行 */
        }
      }
    }
  }
  run()
  return { abort: () => controller.abort() }
}
