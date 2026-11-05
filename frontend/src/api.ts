import type {
  CanvasDetail,
  CanvasSummary,
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
    request<{ ok: boolean; canvas: CanvasDetail; project_dir: string; written_files: string[] }>(
      `/api/canvases/${id}/save`,
      { method: 'POST', body: JSON.stringify(graph) },
    ),
  deleteCanvas: (id: string) =>
    request<{ ok: boolean }>(`/api/canvases/${id}`, { method: 'DELETE' }),
  setCanvasModel: (id: string, cfg: ModelConfig) =>
    request<CanvasDetail>(`/api/canvases/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({ llm_config: cfg }),
    }),

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
}

export interface RunHandle {
  abort: () => void
}

export async function runCanvas(
  canvasId: string,
  input: string,
  onEvent: (evt: RunEvent) => void,
  onError: (message: string) => void,
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
