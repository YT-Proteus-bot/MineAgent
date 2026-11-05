import type {
  CanvasBackground,
  CanvasDetail,
  CanvasSummary,
  ConstraintReport,
  CustomRule,
  GlobalSettings,
  GraphPayload,
  Meta,
  ModelConfig,
  ProjectFileEntry,
  RunEvent,
} from './types'

const BASE = ''

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(BASE + path, {
    ...init,
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
      ...(init?.headers || {}),
    },
  })
  if (!resp.ok) {
    let detail = `${resp.status} ${resp.statusText}`
    try {
      const body = await resp.json()
      detail = body.detail || JSON.stringify(body)
    } catch {
      /* ignore */
    }
    throw new Error(detail)
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

  // ---- AI 助手历史对话 ----
  listChats: () =>
    request<
      { id: string; title: string; message_count: number; updated_at: string }[]
    >('/api/assistant/chats'),
  getChat: (id: string) =>
    request<{ id: string; title: string; messages: ChatMsg[]; updated_at: string }>(
      `/api/assistant/chats/${id}`,
    ),
  saveChat: (payload: {
    messages: ChatMsg[]
    chat_id?: string
    title?: string
    canvas_id?: string
  }) =>
    request<{ ok: boolean; id: string; title?: string }>('/api/assistant/chats', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  deleteChat: (id: string) =>
    request<{ ok: boolean }>(`/api/assistant/chats/${id}`, { method: 'DELETE' }),

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

  assistantStatus: () =>
    request<{ ready: boolean; model: string; base_url: string; hint: string }>(
      '/api/assistant/status',
    ),
}

export interface ChatMsg {
  role: 'user' | 'assistant'
  content: string
}

/** 内置助手：流式对话，token 逐个回调。 */
export async function assistantChat(
  messages: ChatMsg[],
  context: Record<string, any>,
  onToken: (text: string) => void,
  onError: (message: string) => void,
  onDone: () => void,
  signal?: AbortSignal,
): Promise<void> {
  let resp: Response
  try {
    resp = await fetch('/api/assistant/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json; charset=utf-8' },
      body: JSON.stringify({ messages, context }),
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
        const evt = JSON.parse(line.slice(5).trim())
        if (evt.event === 'token') onToken(evt.text)
        else if (evt.event === 'error') onError(evt.message)
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
): Promise<RunHandle> {
  const controller = new AbortController()
  const run = async () => {
    let resp: Response
    try {
      resp = await fetch(`/api/canvases/${canvasId}/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json; charset=utf-8' },
        body: JSON.stringify({ input }),
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
