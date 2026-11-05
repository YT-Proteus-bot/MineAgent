import { create } from 'zustand'
import {
  addEdge,
  applyEdgeChanges,
  applyNodeChanges,
  MarkerType,
  type Connection,
  type EdgeChange,
  type NodeChange,
} from '@xyflow/react'
import { api, runCanvas, type RunHandle } from './api'
import type {
  AgentNode,
  AgentOrg,
  CanvasBackground,
  CanvasDetail,
  CanvasSummary,
  FlowEdge,
  FlowNodeData,
  Meta,
  NodeStatus,
  NodeTypeDef,
  RunEvent,
} from './types'
import { DEFAULT_BACKGROUND } from './types'

export type Toast = { id: number; text: string; kind: 'ok' | 'err' | 'info' }

interface AppState {
  meta: Meta | null
  canvases: CanvasSummary[]
  canvas: CanvasDetail | null
  nodes: AgentNode[]
  edges: FlowEdge[]
  selectedNodeId: string | null
  inspectorTab: 'props' | 'code'
  dirty: boolean
  saving: boolean
  lastSaved: string
  running: boolean
  runEvents: RunEvent[]
  runOutput: string
  runError: string
  runInput: string
  runPanelOpen: boolean
  toasts: Toast[]
  loading: boolean

  init: () => Promise<void>
  loadCanvas: (id: string) => Promise<void>
  createCanvas: (name: string | null, framework: string) => Promise<void>
  renameCanvas: (name: string) => Promise<void>
  deleteCanvas: () => Promise<void>
  changeFramework: (framework: string) => Promise<void>
  refreshCanvases: () => Promise<void>
  setBackground: (patch: Partial<CanvasBackground>) => Promise<void>
  uploadBackground: (file: File) => Promise<void>
  removeBackgroundImage: () => Promise<void>

  onNodesChange: (changes: NodeChange<AgentNode>[]) => void
  onEdgesChange: (changes: EdgeChange<FlowEdge>[]) => void
  onConnect: (conn: Connection) => void
  setSelected: (id: string | null) => void
  setInspectorTab: (tab: 'props' | 'code') => void
  addNode: (kind: string, position: { x: number; y: number }) => void
  updateNode: (id: string, patch: Partial<FlowNodeData>) => void
  updateNodeOrg: (nodeId: string, patch: Partial<AgentOrg>) => void
  setNodeModel: (nodeId: string, cfg: Record<string, any>) => Promise<void>
  clearNodeModel: (nodeId: string) => Promise<void>
  removeNode: (id: string) => void
  duplicateNode: (id: string) => void
  setViewport: (v: { x: number; y: number; zoom: number }) => void

  save: () => Promise<boolean>
  run: (input: string) => Promise<void>
  stopRun: () => void
  setRunInput: (v: string) => void
  setRunPanelOpen: (v: boolean) => void
  setNodeStatus: (id: string, status: NodeStatus) => void
  toast: (text: string, kind?: Toast['kind']) => void
  dismissToast: (id: number) => void
}

let runHandle: RunHandle | null = null
let toastSeq = 1
let initStarted = false

/** 组织关系双向同步：改一处，相关的另一端自动跟着改。 */
export function reconcileOrg(
  nodes: AgentNode[],
  nodeId: string,
  patch: Partial<AgentOrg>,
): AgentNode[] {
  const map = new Map<string, AgentNode>(
    nodes.map((n) => [n.id, { ...n, data: { ...n.data, org: { ...((n.data.org as AgentOrg) || {}) } } }]),
  )
  const getOrg = (id: string): AgentOrg => {
    const n = map.get(id)
    const org = (n?.data.org as AgentOrg) || {}
    return {
      superior: org.superior || '',
      subordinates: [...(org.subordinates || [])],
      peers: [...(org.peers || [])],
    }
  }
  const setOrg = (id: string, org: AgentOrg) => {
    const n = map.get(id)
    if (!n) return
    n.data = {
      ...n.data,
      org: {
        superior: org.superior || '',
        subordinates: [...new Set(org.subordinates || [])].filter((x) => x !== id),
        peers: [...new Set(org.peers || [])].filter((x) => x !== id),
      },
    }
  }

  const mine = getOrg(nodeId)

  // 上级（单向：我认他当上级，他把我加进下级）
  if (patch.superior !== undefined) {
    if (mine.superior && map.has(mine.superior)) {
      const old = getOrg(mine.superior)
      setOrg(mine.superior, { ...old, subordinates: old.subordinates.filter((x) => x !== nodeId) })
    }
    mine.superior = patch.superior || ''
    if (mine.superior && map.has(mine.superior)) {
      const sup = getOrg(mine.superior)
      setOrg(mine.superior, { ...sup, subordinates: [...sup.subordinates, nodeId] })
    }
  }

  // 下级（全量替换：被移除的下级清空上级，新增的下级改认我当上级）
  if (patch.subordinates !== undefined) {
    const next = patch.subordinates.filter((id) => id !== nodeId && map.has(id))
    for (const id of mine.subordinates) {
      if (!next.includes(id) && map.has(id)) {
        const o = getOrg(id)
        if (o.superior === nodeId) setOrg(id, { ...o, superior: '' })
      }
    }
    for (const id of next) {
      const o = getOrg(id)
      if (o.superior && o.superior !== nodeId && map.has(o.superior)) {
        const old = getOrg(o.superior)
        setOrg(o.superior, { ...old, subordinates: old.subordinates.filter((x) => x !== id) })
      }
      setOrg(id, { ...o, superior: nodeId })
    }
    mine.subordinates = next
  }

  // 平级（双向）
  if (patch.peers !== undefined) {
    const next = patch.peers.filter((id) => id !== nodeId && map.has(id))
    for (const id of mine.peers) {
      if (!next.includes(id) && map.has(id)) {
        const o = getOrg(id)
        setOrg(id, { ...o, peers: o.peers.filter((x) => x !== nodeId) })
      }
    }
    for (const id of next) {
      const o = getOrg(id)
      setOrg(id, { ...o, peers: [...o.peers.filter((x) => x !== nodeId), nodeId] })
    }
    mine.peers = next
  }

  setOrg(nodeId, mine)
  return nodes.map((n) => map.get(n.id) || n)
}

function normalize(nodes: AgentNode[]): AgentNode[] {
  return nodes.map((n) => ({ ...n, data: { ...n.data, status: (n.data.status || 'idle') as NodeStatus } }))
}

function edgeLabelFromHandle(handle?: string | null): string | undefined {
  if (!handle || handle === 'out') return undefined
  return handle
}

export const useStore = create<AppState>((set, get) => ({
  meta: null,
  canvases: [],
  canvas: null,
  nodes: [],
  edges: [],
  selectedNodeId: null,
  inspectorTab: 'props',
  dirty: false,
  saving: false,
  lastSaved: '',
  running: false,
  runEvents: [],
  runOutput: '',
  runError: '',
  runInput: '',
  runPanelOpen: false,
  toasts: [],
  loading: true,

  init: async () => {
    if (initStarted) return
    initStarted = true
    set({ loading: true })
    try {
      const meta = await api.meta()
      const canvases = await api.listCanvases()
      set({ meta, canvases })
      if (canvases.length === 0) {
        await get().createCanvas('我的第一个智能体', 'langchain')
      } else {
        await get().loadCanvas(canvases[0].id)
      }
    } catch (err: any) {
      get().toast(`初始化失败：${err.message || err}`, 'err')
    } finally {
      set({ loading: false })
    }
  },

  loadCanvas: async (id) => {
    try {
      const detail = await api.getCanvas(id)
      set({
        canvas: detail,
        nodes: normalize(detail.graph.nodes),
        edges: detail.graph.edges,
        selectedNodeId: null,
        dirty: false,
        runEvents: [],
        runOutput: '',
        runError: '',
      })
    } catch (err: any) {
      get().toast(`打开画布失败：${err.message || err}`, 'err')
    }
  },

  createCanvas: async (name, framework) => {
    try {
      const detail = await api.createCanvas(name, framework)
      await get().refreshCanvases()
      set({
        canvas: detail,
        nodes: normalize(detail.graph.nodes),
        edges: detail.graph.edges,
        selectedNodeId: null,
        dirty: false,
        runEvents: [],
        runOutput: '',
        runError: '',
      })
      get().toast(`已创建画布「${detail.name}」`, 'ok')
    } catch (err: any) {
      get().toast(`创建失败：${err.message || err}`, 'err')
    }
  },

  renameCanvas: async (name) => {
    const canvas = get().canvas
    if (!canvas || !name.trim() || name === canvas.name) return
    try {
      const detail = await api.updateCanvas(canvas.id, { name })
      set({ canvas: detail })
      await get().refreshCanvases()
      get().toast('画布已重命名，项目目录同步更新', 'ok')
    } catch (err: any) {
      get().toast(`重命名失败：${err.message || err}`, 'err')
    }
  },

  deleteCanvas: async () => {
    const canvas = get().canvas
    if (!canvas) return
    try {
      await api.deleteCanvas(canvas.id)
      const list = await api.listCanvases()
      set({ canvases: list })
      if (list.length) {
        await get().loadCanvas(list[0].id)
      } else {
        await get().createCanvas('我的第一个智能体', 'langchain')
      }
      get().toast('画布已删除', 'ok')
    } catch (err: any) {
      get().toast(`删除失败：${err.message || err}`, 'err')
    }
  },

  changeFramework: async (framework) => {
    const canvas = get().canvas
    if (!canvas || canvas.framework === framework) return
    try {
      const detail = await api.updateCanvas(canvas.id, { framework })
      set({
        canvas: detail,
        nodes: normalize(detail.graph.nodes),
        edges: detail.graph.edges,
        selectedNodeId: null,
        dirty: false,
      })
      const fw = get().meta?.frameworks.find((f) => f.id === framework)
      get().toast(`已切换到 ${fw?.label || framework}，架构图已重建并落盘`, 'ok')
    } catch (err: any) {
      get().toast(`切换框架失败：${err.message || err}`, 'err')
    }
  },

  refreshCanvases: async () => {
    try {
      set({ canvases: await api.listCanvases() })
    } catch {
      /* ignore */
    }
  },

  setBackground: async (patch) => {
    const canvas = get().canvas
    if (!canvas) return
    const next: CanvasBackground = { ...DEFAULT_BACKGROUND, ...canvas.background, ...patch }
    // 背景是即改即存的显示设置，不参与「未保存」计数
    set({ canvas: { ...get().canvas!, background: next } })
    try {
      await api.setBackground(canvas.id, next)
    } catch (err: any) {
      get().toast(`背景保存失败：${err.message || err}`, 'err')
    }
  },

  uploadBackground: async (file) => {
    const canvas = get().canvas
    if (!canvas) return
    try {
      const res = await api.uploadBackground(canvas.id, file)
      set({ canvas: { ...get().canvas!, background: res.background } })
      get().toast(`背景图已更新（${Math.max(1, Math.round(res.size / 1024))} KB）`, 'ok')
    } catch (err: any) {
      get().toast(`上传失败：${err.message || err}`, 'err')
    }
  },

  removeBackgroundImage: async () => {
    const canvas = get().canvas
    if (!canvas) return
    try {
      const res = await api.deleteBackground(canvas.id)
      set({ canvas: { ...get().canvas!, background: res.background } })
      get().toast('背景图已移除', 'ok')
    } catch (err: any) {
      get().toast(`移除失败：${err.message || err}`, 'err')
    }
  },

  onNodesChange: (changes) => {
    const next = applyNodeChanges<AgentNode>(changes as NodeChange<AgentNode>[], get().nodes)
    // 尺寸测量、选中变化不算「改动了画布内容」
    const meaningful = changes.some((c) => c.type !== 'dimensions' && c.type !== 'select')
    set({ nodes: next, dirty: meaningful ? true : get().dirty })
  },

  onEdgesChange: (changes) => {
    const next = applyEdgeChanges<FlowEdge>(changes as EdgeChange<FlowEdge>[], get().edges)
    const meaningful = changes.some((c) => c.type !== 'select')
    set({ edges: next, dirty: meaningful ? true : get().dirty })
  },

  onConnect: (conn) => {
    const edge: FlowEdge = {
      ...conn,
      id: `e_${conn.source}_${conn.sourceHandle || 'out'}_${conn.target}_${Date.now().toString(36)}`,
      type: 'smoothstep',
      animated: false,
      label: edgeLabelFromHandle(conn.sourceHandle),
      data: { branch: edgeLabelFromHandle(conn.sourceHandle) },
      markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16, color: '#7c8aa5' },
      style: { stroke: '#7c8aa5', strokeWidth: 2 },
    }
    set({ edges: addEdge(edge, get().edges) as FlowEdge[], dirty: true })
  },

  setSelected: (id) => set({ selectedNodeId: id }),
  setInspectorTab: (tab) => set({ inspectorTab: tab }),

  addNode: (kind, position) => {
    const meta = get().meta
    const def: NodeTypeDef | undefined = meta?.nodes.find((n) => n.kind === kind)
    if (!def) return
    const existing = get().nodes.filter((n) => n.data.kind === kind).length + 1
    const params: Record<string, any> = {}
    def.params.forEach((p) => {
      params[p.key] = p.default
    })
    const id = `n_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 6)}`
    const node: AgentNode = {
      id,
      type: 'agent',
      position,
      data: {
        kind,
        label: def.label,
        name: `${kind}_${existing}`,
        description: def.description,
        code: (def as any).default_code || '',
        language: def.language,
        params,
        status: 'idle',
      },
    }
    set({ nodes: [...get().nodes, node], dirty: true, selectedNodeId: id })
  },

  updateNode: (id, patch) => {
    set({
      nodes: get().nodes.map((n) => (n.id === id ? { ...n, data: { ...n.data, ...patch } } : n)),
      dirty: true,
    })
  },

  updateNodeOrg: (nodeId, patch) => {
    set({ nodes: reconcileOrg(get().nodes, nodeId, patch), dirty: true })
  },

  setNodeModel: async (nodeId, cfg) => {
    const canvas = get().canvas
    if (!canvas) return
    try {
      const res = await api.setNodeModel(canvas.id, nodeId, cfg)
      set({
        nodes: get().nodes.map((n) =>
          n.id === nodeId
            ? { ...n, data: { ...n.data, model: { ...(n.data.model || {}), ...res } } }
            : n,
        ),
        dirty: true,
      })
      get().toast('模型配置已保存，点「保存」后才会写进项目', 'ok')
    } catch (err: any) {
      get().toast(`模型配置保存失败：${err.message || err}`, 'err')
    }
  },

  clearNodeModel: async (nodeId) => {
    const canvas = get().canvas
    if (!canvas) return
    try {
      await api.clearNodeModel(canvas.id, nodeId)
      set({
        nodes: get().nodes.map((n) =>
          n.id === nodeId ? { ...n, data: { ...n.data, model: null } } : n,
        ),
        dirty: true,
      })
      get().toast('已恢复为跟随画布 / 全局模型', 'ok')
    } catch (err: any) {
      get().toast(`清除失败：${err.message || err}`, 'err')
    }
  },

  removeNode: (id) => {
    // 删掉节点时，顺手把它从别人的组织关系里摘掉，避免留下悬空引用
    const rest = get()
      .nodes.filter((n) => n.id !== id)
      .map((n) => {
        const org = (n.data.org as AgentOrg) || ({} as AgentOrg)
        const next: AgentOrg = {
          superior: org.superior === id ? '' : org.superior || '',
          subordinates: (org.subordinates || []).filter((x) => x !== id),
          peers: (org.peers || []).filter((x) => x !== id),
        }
        return { ...n, data: { ...n.data, org: next } }
      })
    set({
      nodes: rest,
      edges: get().edges.filter((e) => e.source !== id && e.target !== id),
      selectedNodeId: get().selectedNodeId === id ? null : get().selectedNodeId,
      dirty: true,
    })
  },

  duplicateNode: (id) => {
    const src = get().nodes.find((n) => n.id === id)
    if (!src) return
    const newId = `n_${Date.now().toString(36)}`
    const copy: AgentNode = {
      ...src,
      id: newId,
      position: { x: src.position.x + 40, y: src.position.y + 60 },
      selected: false,
      data: { ...src.data, name: `${src.data.name}_copy`, status: 'idle' },
    }
    set({ nodes: [...get().nodes, copy], selectedNodeId: newId, dirty: true })
  },

  setViewport: (v) => {
    const canvas = get().canvas
    if (!canvas) return
    set({ canvas: { ...canvas, graph: { ...canvas.graph, viewport: v } } })
  },

  save: async () => {
    const { canvas, nodes, edges } = get()
    if (!canvas) return false
    const kinds = nodes.map((n) => n.data.kind)
    if (!kinds.includes('input')) {
      get().toast('画布缺少「输入 Input」节点，运行时会失败', 'err')
      return false
    }
    if (!kinds.includes('output')) {
      get().toast('画布缺少「输出 Output」节点，请先补一个', 'err')
      return false
    }
    set({ saving: true })
    try {
      const cleanNodes = nodes.map((n) => ({
        ...n,
        selected: false,
        data: { ...n.data, status: 'idle' as NodeStatus },
      }))
      const res = await api.saveCanvas(canvas.id, {
        nodes: cleanNodes,
        edges,
        viewport: canvas.graph.viewport || { x: 0, y: 0, zoom: 1 },
        background: canvas.background,
      })
      set({
        canvas: res.canvas,
        nodes: normalize(res.canvas.graph.nodes),
        edges: res.canvas.graph.edges,
        dirty: false,
        lastSaved: new Date().toLocaleTimeString('zh-CN'),
      })
      await get().refreshCanvases()
      get().toast(`已保存：${res.written_files.length} 个文件写入 ${res.project_dir.split(/[\\/]/).pop()}`, 'ok')
      return true
    } catch (err: any) {
      get().toast(`保存失败：${err.message || err}`, 'err')
      return false
    } finally {
      set({ saving: false })
    }
  },

  run: async (input) => {
    const canvas = get().canvas
    if (!canvas) return
    if (get().running) return
    const saved = get().dirty ? await get().save() : true
    if (!saved) return

    set({
      running: true,
      runEvents: [],
      runOutput: '',
      runError: '',
      runPanelOpen: true,
      nodes: get().nodes.map((n) => ({ ...n, data: { ...n.data, status: 'idle' as NodeStatus } })),
    })

    const names: Record<string, string> = {}
    get().nodes.forEach((n) => {
      names[n.id] = n.data.name
    })

    runHandle = await runCanvas(
      canvas.id,
      input,
      (evt) => {
        const events = [...get().runEvents, evt]
        set({ runEvents: events.slice(-400) })
        if (evt.event === 'node_start' && evt.node) {
          set({
            nodes: get().nodes.map((n) =>
              n.id === evt.node ? { ...n, data: { ...n.data, status: 'running' as NodeStatus } } : n,
            ),
          })
        }
        if (evt.event === 'node_end' && evt.node) {
          set({
            nodes: get().nodes.map((n) =>
              n.id === evt.node
                ? {
                    ...n,
                    data: {
                      ...n.data,
                      status: 'done' as NodeStatus,
                      durationMs: evt.duration_ms,
                    },
                  }
                : n,
            ),
          })
        }
        if (evt.event === 'error') {
          set({ runError: String(evt.message || '运行出错') })
          const bad = evt.node
          if (bad) {
            set({
              nodes: get().nodes.map((n) =>
                n.id === bad ? { ...n, data: { ...n.data, status: 'error' as NodeStatus } } : n,
              ),
            })
          }
        }
        if (evt.event === 'run_end') {
          set({
            running: false,
            runOutput:
              typeof evt.output === 'string'
                ? evt.output
                : JSON.stringify(evt.output ?? '', null, 2),
          })
        }
      },
      (msg) => {
        set({ running: false, runError: msg })
        get().toast(msg, 'err')
      },
    )
  },

  stopRun: () => {
    runHandle?.abort()
    runHandle = null
    set({ running: false, runError: '已手动停止' })
  },

  setRunInput: (v) => set({ runInput: v }),
  setRunPanelOpen: (v) => set({ runPanelOpen: v }),

  setNodeStatus: (id, status) => {
    set({
      nodes: get().nodes.map((n) => (n.id === id ? { ...n, data: { ...n.data, status } } : n)),
    })
  },

  toast: (text, kind = 'info') => {
    const id = toastSeq++
    set({ toasts: [...get().toasts, { id, text, kind }] })
    setTimeout(() => get().dismissToast(id), 4200)
  },

  dismissToast: (id) => set({ toasts: get().toasts.filter((t) => t.id !== id) }),
}))
