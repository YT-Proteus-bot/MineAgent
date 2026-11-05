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
  ConstraintReport,
  CustomRule,
  FlowEdge,
  FlowNodeData,
  Meta,
  NodeStatus,
  NodeTypeDef,
  RunEvent,
} from './types'
import { DEFAULT_BACKGROUND, isAgentKind } from './types'

/** 会跑 Agent 循环的节点类型（新增时需要带上画布默认模式） */
function isAgentLike(kind: string): boolean {
  return isAgentKind(kind)
}

export type Toast = { id: number; text: string; kind: 'ok' | 'err' | 'info' }

/** 撤销 / 重做用的画布快照 */
export type CanvasSnapshot = { nodes: AgentNode[]; edges: FlowEdge[] }

const HISTORY_LIMIT = 60

let snapshotTimer: ReturnType<typeof setTimeout> | null = null
let currentSnapshot: CanvasSnapshot | null = null
let suspendHistory = false

function snapshotKey(s: CanvasSnapshot): string {
  return JSON.stringify({
    n: s.nodes.map((n) => [n.id, n.position.x, n.position.y, n.width, n.height, n.data]),
    e: s.edges.map((e) => [e.id, e.source, e.target, e.sourceHandle]),
  })
}

function takeSnapshot(state: { nodes: AgentNode[]; edges: FlowEdge[] }): CanvasSnapshot {
  return { nodes: state.nodes, edges: state.edges }
}

/* ------------------------------------------------------------------ */
/* 新增节点时的自动连线建议                                            */
/* ------------------------------------------------------------------ */
const AGENT_KINDS = new Set([
  'agent', 'worker', 'supervisor', 'autogen_assistant', 'autogen_tool_agent',
  'autogen_group_chat', 'crewai_agent', 'crewai_crew', 'group_chat', 'debate',
])
const TOOL_KINDS = new Set([
  'tool', 'function', 'mcp_tool', 'crewai_tool', 'http_request', 'web_search',
  'code_interpreter', 'sql_query', 'rag_retriever', 'file_io', 'browser', 'shell',
])

const NEW_NODE = '__new__'

export function buildEdge(source: string, target: string, sourceHandle?: string | null): FlowEdge {
  const handle = sourceHandle || 'out'
  return {
    id: `e_${source}_${handle}_${target}_${Date.now().toString(36)}_${Math.random()
      .toString(36)
      .slice(2, 5)}`,
    source,
    target,
    sourceHandle: handle,
    targetHandle: 'in',
    type: 'agent',
    label: handle !== 'out' ? handle : undefined,
    data: { branch: handle !== 'out' ? handle : undefined },
  } as FlowEdge
}

/**
 * 给新节点挑连线：
 * - 新加 output → 接到当前末端节点
 * - 有选中节点 → 从它连出，并把原来的下一跳串到新节点后面（插入）
 * - 没选中 → 连到最近的可接上游（工具类节点优先挂到 agent 下游）
 * - 找不到合法上游、或新节点是 input 时不连，保持孤立
 * 所有选择都遵守约束：output 不能有出边、input 不能有入边、不重复连。
 */
export function suggestLinks(args: {
  kind: string
  position: { x: number; y: number }
  nodes: AgentNode[]
  edges: FlowEdge[]
  selectedId: string | null
  outputs: string
}): { links: { source: string; target: string; handle: string }[]; remove: FlowEdge[]; note: string } {
  const { kind, position, nodes, edges, selectedId, outputs } = args
  const links: { source: string; target: string; handle: string }[] = []
  const remove: FlowEdge[] = []
  let note = ''
  if (!nodes.length) return { links, remove, note }

  const meta = useStore.getState().meta
  const kindOf = (id: string) => nodes.find((n) => n.id === id)?.data.kind || ''
  const labelOf = (id: string) => nodes.find((n) => n.id === id)?.data.label || '节点'
  const centerOf = (n: AgentNode) => ({
    x: n.position.x + (Number(n.width) || 216) / 2,
    y: n.position.y + (Number(n.height) || 90) / 2,
  })
  const distTo = (n: AgentNode) =>
    Math.hypot(centerOf(n).x - position.x, centerOf(n).y - position.y)
  const outEdges = (id: string) => edges.filter((e) => e.source === id)
  const outPortsOf = (id: string): string[] => {
    const def = meta?.nodes.find((n) => n.kind === kindOf(id))
    return def?.outputs?.length ? def.outputs : ['out']
  }
  // 多端口节点优先接还没用过的出口
  const pickHandle = (id: string): string => {
    const ports = outPortsOf(id)
    const used = new Set(outEdges(id).map((e) => e.sourceHandle || 'out'))
    return ports.find((p) => !used.has(p)) || ports[0] || 'out'
  }

  if (kind === 'output') {
    const terminals = nodes
      .filter((n) => n.data.kind !== 'output' && outEdges(n.id).length === 0)
      .sort((a, b) => distTo(a) - distTo(b))
    if (terminals.length) {
      links.push({ source: terminals[0].id, target: NEW_NODE, handle: 'out' })
      note = `已自动接到末端「${terminals[0].data.label}」`
    }
    return { links, remove, note }
  }

  if (kind === 'input') {
    // 输入节点是起点，不自动接上游
    return { links, remove, note }
  }

  let sourceId: string | null = null
  let insertMode = false

  const sel = selectedId ? nodes.find((n) => n.id === selectedId) : null
  if (sel && sel.data.kind !== 'output') {
    sourceId = sel.id
    insertMode = true
  } else {
    const pool = nodes.filter((n) => n.data.kind !== 'output')
    const preferAgent = TOOL_KINDS.has(kind) && pool.some((n) => AGENT_KINDS.has(n.data.kind))
    const narrowed = preferAgent ? pool.filter((n) => AGENT_KINDS.has(n.data.kind)) : pool
    const nearest = [...narrowed].sort((a, b) => distTo(a) - distTo(b))[0]
    if (nearest && distTo(nearest) < 720) sourceId = nearest.id
  }

  if (!sourceId) return { links, remove, note }

  const handle = pickHandle(sourceId)
  links.push({ source: sourceId, target: NEW_NODE, handle })
  note = `已自动从「${labelOf(sourceId)}」连过来`

  // 选中后新增：把原来那条边拆开，新节点插中间
  if (insertMode) {
    const outs = outEdges(sourceId)
    if (outs.length === 1) {
      const nextId = outs[0].target
      remove.push(outs[0])
      links.push({ source: NEW_NODE, target: nextId, handle: outputs })
      note = `已插入到「${labelOf(sourceId)}」与「${labelOf(nextId)}」之间`
    }
  }

  return { links, remove, note }
}

interface AppState {
  meta: Meta | null
  canvases: CanvasSummary[]
  canvas: CanvasDetail | null
  nodes: AgentNode[]
  edges: FlowEdge[]
  selectedNodeId: string | null
  inspectorTab: 'props' | 'code'
  rightTab: 'assistant' | 'node'
  highlightedNodeIds: string[]
  dirty: boolean
  saving: boolean
  lastSaved: string
  running: boolean
  runEvents: RunEvent[]
  runOutput: string
  runStream: { node: string; name: string; text: string } | null
  runError: string
  runInput: string
  runPanelOpen: boolean
  toasts: Toast[]
  loading: boolean
  constraintReport: ConstraintReport | null
  violatedNodeIds: string[]
  constraintPanelOpen: boolean
  historyPast: CanvasSnapshot[]
  historyFuture: CanvasSnapshot[]
  savedSnapshotKey: string

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
  validateNow: () => Promise<void>
  undo: () => void
  redo: () => void
  resetHistory: () => void
  setConstraintPanelOpen: (v: boolean) => void
  addRule: (rule: CustomRule) => Promise<void>
  removeRule: (ruleId: string) => Promise<void>

  onNodesChange: (changes: NodeChange<AgentNode>[]) => void
  onEdgesChange: (changes: EdgeChange<FlowEdge>[]) => void
  onConnect: (conn: Connection) => void
  connectNodes: (source: string, target: string, sourceHandle?: string | null) => void
  setSelected: (id: string | null) => void
  setInspectorTab: (tab: 'props' | 'code') => void
  setRightTab: (tab: 'assistant' | 'node') => void
  openNodePanel: (id: string, tab?: 'props' | 'code') => void
  setHighlightedNodes: (ids: string[]) => void
  updateEdgeData: (edgeId: string, patch: Record<string, any>) => void
  updateEdgeEndpoint: (edgeId: string, which: 'source' | 'target', nodeId: string) => void
  removeEdge: (edgeId: string) => void
  addNode: (kind: string, position: { x: number; y: number }) => void
  updateNode: (id: string, patch: Partial<FlowNodeData>) => void
  updateNodeOrg: (nodeId: string, patch: Partial<AgentOrg>) => void
  setNodeModel: (nodeId: string, cfg: Record<string, any>) => Promise<void>
  clearNodeModel: (nodeId: string) => Promise<void>
  removeNode: (id: string) => void
  duplicateNode: (id: string) => void
  resetNodeSize: (id: string) => void
  autoLayout: () => void
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
  rightTab: 'assistant',
  highlightedNodeIds: [],
  dirty: false,
  saving: false,
  lastSaved: '',
  running: false,
  runEvents: [],
  runOutput: '',
  runStream: null,
  runError: '',
  runInput: '',
  runPanelOpen: false,
  toasts: [],
  loading: true,
  constraintReport: null,
  violatedNodeIds: [],
  constraintPanelOpen: false,
  historyPast: [],
  historyFuture: [],
  savedSnapshotKey: '',

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
        constraintReport: null,
        violatedNodeIds: [],
      })
      get().resetHistory()
      get().validateNow()
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
        constraintReport: null,
        violatedNodeIds: [],
      })
      get().toast(`已创建画布「${detail.name}」`, 'ok')
      get().resetHistory()
      get().validateNow()
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

  validateNow: async () => {
    const canvas = get().canvas
    if (!canvas) return
    try {
      const report = await api.validateCanvas(canvas.id, {
        nodes: get().nodes,
        edges: get().edges,
        viewport: canvas.graph.viewport || { x: 0, y: 0, zoom: 1 },
        background: canvas.background,
      })
      set({ constraintReport: report, violatedNodeIds: report.node_ids || [] })
    } catch {
      /* 校验失败不影响画布编辑 */
    }
  },

  undo: () => {
    const past = get().historyPast
    if (!past.length) return
    const prev = past[past.length - 1]
    const cur = takeSnapshot(get())
    suspendHistory = true
    if (snapshotTimer) clearTimeout(snapshotTimer)
    set({
      nodes: prev.nodes,
      edges: prev.edges,
      historyPast: past.slice(0, -1),
      historyFuture: [cur, ...get().historyFuture].slice(0, HISTORY_LIMIT),
      selectedNodeId: null,
      dirty: snapshotKey(prev) !== get().savedSnapshotKey,
    })
    currentSnapshot = prev
    setTimeout(() => {
      suspendHistory = false
    }, 60)
    get().toast('已撤销', 'info')
  },

  redo: () => {
    const future = get().historyFuture
    if (!future.length) return
    const next = future[0]
    const cur = takeSnapshot(get())
    suspendHistory = true
    if (snapshotTimer) clearTimeout(snapshotTimer)
    set({
      nodes: next.nodes,
      edges: next.edges,
      historyPast: [...get().historyPast, cur].slice(-HISTORY_LIMIT),
      historyFuture: future.slice(1),
      selectedNodeId: null,
      dirty: snapshotKey(next) !== get().savedSnapshotKey,
    })
    currentSnapshot = next
    setTimeout(() => {
      suspendHistory = false
    }, 60)
    get().toast('已重做', 'info')
  },

  resetHistory: () => {
    suspendHistory = true
    if (snapshotTimer) clearTimeout(snapshotTimer)
    currentSnapshot = takeSnapshot(get())
    set({
      historyPast: [],
      historyFuture: [],
      savedSnapshotKey: currentSnapshot ? snapshotKey(currentSnapshot) : '',
    })
    setTimeout(() => {
      suspendHistory = false
    }, 60)
  },

  setConstraintPanelOpen: (v) => set({ constraintPanelOpen: v }),

  addRule: async (rule) => {
    const canvas = get().canvas
    if (!canvas) return
    const next = [...(canvas.rules || []), rule]
    try {
      const res = await api.setRules(canvas.id, next)
      set({ canvas: { ...get().canvas!, rules: res.rules } })
      await get().validateNow()
      get().toast('约束规则已添加', 'ok')
    } catch (err: any) {
      get().toast(`添加规则失败：${err.message || err}`, 'err')
    }
  },

  removeRule: async (ruleId) => {
    const canvas = get().canvas
    if (!canvas) return
    const next = (canvas.rules || []).filter((r) => r.id !== ruleId)
    try {
      const res = await api.setRules(canvas.id, next)
      set({ canvas: { ...get().canvas!, rules: res.rules } })
      await get().validateNow()
    } catch (err: any) {
      get().toast(`删除规则失败：${err.message || err}`, 'err')
    }
  },

  onNodesChange: (changes) => {
    const next = applyNodeChanges<AgentNode>(changes as NodeChange<AgentNode>[], get().nodes)
    // 选中变化、初始尺寸测量不算改动；用户手动拖边框缩放（resizing）要算
    const meaningful = changes.some((c) => {
      const anyChange = c as any
      if (anyChange.type === 'select') return false
      if (anyChange.type === 'dimensions') return !!anyChange.resizing
      return true
    })
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
  setRightTab: (tab) => set({ rightTab: tab }),
  openNodePanel: (id, tab = 'props') =>
    set({ selectedNodeId: id, rightTab: 'node', inspectorTab: tab }),

  setHighlightedNodes: (ids) => set({ highlightedNodeIds: ids }),

  updateEdgeData: (edgeId, patch) => {
    set({
      edges: get().edges.map((e) =>
        e.id === edgeId ? { ...e, data: { ...(e.data || {}), ...patch } } : e,
      ),
      dirty: true,
    })
  },

  updateEdgeEndpoint: (edgeId, which, nodeId) => {
    const edges = get().edges
    const edge = edges.find((e) => e.id === edgeId)
    if (!edge) return
    const nodes = get().nodes
    const src = which === 'source' ? nodeId : edge.source
    const dst = which === 'target' ? nodeId : edge.target
    const kindOf = (id: string) => nodes.find((n) => n.id === id)?.data.kind || ''
    const labelOf = (id: string) => nodes.find((n) => n.id === id)?.data.label || id

    if (src === dst) {
      get().toast('连线两端不能是同一个节点', 'err')
      return
    }
    if (kindOf(src) === 'output') {
      get().toast('输出节点不能作为连线起点', 'err')
      return
    }
    if (kindOf(dst) === 'input') {
      get().toast('输入节点不能作为连线终点', 'err')
      return
    }
    if (edges.some((e) => e.id !== edgeId && e.source === src && e.target === dst)) {
      get().toast('这两个节点之间已经有连线了', 'info')
      return
    }

    set({
      edges: edges.map((e) => (e.id === edgeId ? { ...e, [which]: nodeId } : e)),
      highlightedNodeIds: [src, dst],
      dirty: true,
    })
    get().toast(
      which === 'source'
        ? `起点已改为「${labelOf(nodeId)}」`
        : `终点已改为「${labelOf(nodeId)}」`,
      'ok',
    )
  },

  removeEdge: (edgeId) => {
    set({ edges: get().edges.filter((e) => e.id !== edgeId), dirty: true })
  },

  connectNodes: (source, target, sourceHandle) => {
    if (source === target) {
      get().toast('节点不能连到自己', 'err')
      return
    }
    const handle = sourceHandle || 'out'
    const dup = get().edges.some(
      (e) => e.source === source && e.target === target && (e.sourceHandle || 'out') === handle,
    )
    if (dup) {
      get().toast('这条连线已经存在了', 'info')
      return
    }
    get().onConnect({ source, target, sourceHandle: handle, targetHandle: 'in' })
    const targetNode = get().nodes.find((n) => n.id === target)
    get().toast(`已连接到「${targetNode?.data.label || target}」`, 'ok')
  },

  addNode: (kind, position) => {
    const meta = get().meta
    const def: NodeTypeDef | undefined = meta?.nodes.find((n) => n.kind === kind)
    if (!def) return
    const nodes = get().nodes
    const edges = get().edges
    // 名字要避开已有节点，否则后端去重会改名，导致代码里的函数名跟着变
    const usedNames = new Set(nodes.map((n) => n.data.name))
    let seq = nodes.filter((n) => n.data.kind === kind).length + 1
    while (usedNames.has(`${kind}_${seq}`)) seq += 1
    const existing = seq
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
        // 新增节点直接用 agent.py 的原生块，和保存后保持一致
        code: (def as any).native_code || (def as any).default_code || '',
        // 预览跑的是 run(ctx) 版本（没装框架时降级用）
        preview_code: (def as any).default_code || '',
        language: def.language,
        params,
        status: 'idle',
      },
    }
    // agent 节点默认用画布选的模式
    const canvasMode = get().canvas?.mode
    if (canvasMode && isAgentLike(kind)) {
      node.data.params = { ...node.data.params, mode: canvasMode }
    }

    const auto = suggestLinks({
      kind,
      position,
      nodes,
      edges,
      selectedId: get().selectedNodeId,
      outputs: (def.outputs && def.outputs.length ? def.outputs : ['out'])[0],
    })
    const newEdges: FlowEdge[] = auto.links.map((l) =>
      buildEdge(
        l.source === NEW_NODE ? id : l.source,
        l.target === NEW_NODE ? id : l.target,
        l.handle,
      ),
    )
    const removed = new Set(auto.remove.map((e) => e.id))
    const keptEdges = edges.filter((e) => !removed.has(e.id))

    set({
      nodes: [...nodes, node],
      edges: [...keptEdges, ...newEdges],
      dirty: true,
      selectedNodeId: id,
    })
    if (auto.note) get().toast(auto.note, 'info')
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

  resetNodeSize: (id) => {
    set({
      nodes: get().nodes.map((n) =>
        n.id === id ? { ...n, width: undefined, height: undefined } : n,
      ),
      dirty: true,
    })
  },

  /** 按拓扑分层重排节点，尽量把线拉成水平的一条条，减少交叉 */
  autoLayout: () => {
    const nodes = get().nodes
    const edges = get().edges
    if (!nodes.length) return

    const ids = nodes.map((n) => n.id)
    const byId = new Map(nodes.map((n) => [n.id, n]))
    const kindOf = (id: string) => byId.get(id)?.data.kind || ''
    // 用真实渲染尺寸（measured）优先，其次用户拖出来的显式尺寸，最后才用默认值
    const widthOf = (id: string) =>
      Number(byId.get(id)?.measured?.width) || Number(byId.get(id)?.width) || 216
    const heightOf = (id: string) =>
      Number(byId.get(id)?.measured?.height) || Number(byId.get(id)?.height) || 92

    // ── 1. 分层：从 input 出发做 BFS，input 在最上、output 固定在最下 ──
    // 用 BFS（最短路径）而不是最长路径：回边不会把层数越拉越多
    const layer: Record<string, number> = {}
    const succ: Record<string, string[]> = {}
    ids.forEach((id) => {
      succ[id] = []
    })
    for (const e of edges) {
      if (succ[e.source] && succ[e.target]) succ[e.source].push(e.target)
    }

    const inputIds = ids.filter((id) => kindOf(id) === 'input')
    const seeds = inputIds.length
      ? inputIds
      : ids.filter((id) => !edges.some((e) => e.target === id))
    const queue: string[] = []
    ;(seeds.length ? seeds : [ids[0]]).forEach((id) => {
      layer[id] = 0
      queue.push(id)
    })
    while (queue.length) {
      const cur = queue.shift() as string
      for (const nxt of succ[cur]) {
        if (layer[nxt] === undefined) {
          layer[nxt] = layer[cur] + 1
          queue.push(nxt)
        }
      }
    }
    // 从 input 走不到的节点（孤立/只有入边在环里）先放 0，后面统一处理
    ids.forEach((id) => {
      if (layer[id] === undefined) layer[id] = 0
    })
    // output 固定放最后一层
    const maxNormal = Math.max(
      ...ids.filter((id) => kindOf(id) !== 'output').map((id) => layer[id]),
      0,
    )
    ids.forEach((id) => {
      if (kindOf(id) === 'output') layer[id] = maxNormal + 1
    })

    // 按层分组，层内先按原顺序（保持大致相对位置）
    const maxLayer = Math.max(...ids.map((id) => layer[id]))
    const layers: string[][] = Array.from({ length: maxLayer + 1 }, () => [])
    ids.forEach((id) => {
      layers[layer[id]].push(id)
    })
    layers.forEach((arr) =>
      arr.sort((a, b) => (byId.get(a)?.position.x || 0) - (byId.get(b)?.position.x || 0)),
    )

    // ── 2. 重心排序：把每个节点挪到"它的上游节点平均位置"附近，减少交叉 ──
    const indexIn = (id: string, arr: string[]) => arr.indexOf(id)
    const barycenter = (id: string, refLayer: string[], down: boolean) => {
      const neighbors = edges
        .filter((e) => (down ? e.target === id : e.source === id))
        .map((e) => (down ? e.source : e.target))
        .filter((nid) => refLayer.includes(nid))
      if (!neighbors.length) return null
      const sum = neighbors.reduce((acc, nid) => acc + indexIn(nid, refLayer), 0)
      return sum / neighbors.length
    }

    for (let round = 0; round < 4; round++) {
      const down = round % 2 === 0
      const order = down
        ? layers.map((_, i) => i).slice(1)
        : layers.map((_, i) => i).slice(0, -1).reverse()
      for (const li of order) {
        const arr = layers[li]
        if (arr.length < 2) continue
        const ref = layers[down ? li - 1 : li + 1]
        if (!ref || !ref.length) continue
        const score = new Map<string, number>()
        arr.forEach((id, i) => {
          const b = barycenter(id, ref, down)
          score.set(id, b === null ? i : b)
        })
        arr.sort((a, b) => (score.get(a) as number) - (score.get(b) as number))
      }
    }

    // ── 3. 定位：横向分层（input 最左、output 最右），层间距给足 ──
    // handle 在左右两侧，横向排布时线最短、最直，交叉也最少
    // 间距按最宽/最高的节点自适应，避免被拉伸过的节点互相压住
    const maxW = Math.max(...ids.map(widthOf), 216)
    const maxH = Math.max(...ids.map(heightOf), 92)
    const LAYER_GAP = Math.max(340, maxW + 140) // 上下游之间的距离，留给线上的分支名
    const ROW_GAP = Math.max(140, maxH + 90) // 同一层上下之间的距离
    const maxRowCount = Math.max(...layers.map((arr) => arr.length))
    const canvasH =
      maxRowCount * 92 + Math.max(maxRowCount - 1, 0) * ROW_GAP
    const pos: Record<string, { x: number; y: number }> = {}
    layers.forEach((arr, li) => {
      const totalH =
        arr.reduce((acc, id) => acc + heightOf(id), 0) + Math.max(arr.length - 1, 0) * ROW_GAP
      let cursorY = (canvasH - totalH) / 2
      arr.forEach((id) => {
        pos[id] = { x: Math.round(li * LAYER_GAP), y: Math.round(cursorY) }
        cursorY += heightOf(id) + ROW_GAP
      })
    })

    // 以原图中心为基准平移，避免整图跳到原点
    const originX = Math.min(...nodes.map((n) => n.position.x))
    const originY = Math.min(...nodes.map((n) => n.position.y))
    const newMinX = Math.min(...Object.values(pos).map((p) => p.x))
    const newMinY = Math.min(...Object.values(pos).map((p) => p.y))
    const shiftX = originX - newMinX
    const shiftY = originY - newMinY

    set({
      nodes: nodes.map((n) => {
        const p = pos[n.id]
        return p ? { ...n, position: { x: p.x + shiftX, y: p.y + shiftY } } : n
      }),
      dirty: true,
    })
    get().toast('已按上下游重新排布：输入在左、输出在右', 'ok')
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
        constraintReport: res.constraints ?? get().constraintReport,
        violatedNodeIds: res.constraints?.node_ids ?? get().violatedNodeIds,
        savedSnapshotKey: snapshotKey({
          nodes: normalize(res.canvas.graph.nodes),
          edges: res.canvas.graph.edges,
        }),
      })
      await get().refreshCanvases()
      get().toast(`已保存：${res.written_files.length} 个文件写入 ${res.project_dir.split(/[\\/]/).pop()}`, 'ok')
      if (res.constraints && res.constraints.counts.error > 0) {
        get().toast(`注意：还有 ${res.constraints.counts.error} 条约束未满足，运行时会被拦下`, 'err')
      }
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
      runStream: null,
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
        if (evt.event === 'token') {
          const node = String(evt.node || '')
          const text = String(evt.text || '')
          if (text) {
            const prev = get().runStream
            set({
              runStream:
                prev && prev.node === node
                  ? { ...prev, text: (prev.text + text).slice(-6000) }
                  : { node, name: String(evt.name || ''), text },
            })
          }
        }
        if (evt.event === 'node_start' && evt.node) {
          set({
            runStream: { node: String(evt.node), name: String(evt.name || ''), text: '' },
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
          set({ runError: String(evt.message || '运行出错'), runStream: null })
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
            runStream: null,
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
      (detail) => {
        // 约束不满足被拦下：直接打开约束面板，让人看到差在哪
        set({
          running: false,
          runError: detail.message,
          constraintPanelOpen: true,
          constraintReport: {
            ok: false,
            errors: detail.violations as any,
            warnings: [],
            infos: [],
            violations: detail.violations as any,
            counts: { error: detail.violations.length, warn: 0, info: 0 },
            node_ids: [
              ...new Set(detail.violations.flatMap((v: any) => v.nodes || [])),
            ] as string[],
            checked_rules: 0,
          },
        })
        set({ violatedNodeIds: get().constraintReport?.node_ids || [] })
        get().toast(detail.message, 'err')
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

// --------------------------------------------------------------------------- //
// 撤销 / 重做：监听画布内容变化，停顿 450ms 后记一步
// 连续拖动、连续输入会被合并成一步，不会产生一长串没意义的中间状态
// --------------------------------------------------------------------------- //
useStore.subscribe((state, prev) => {
  if (suspendHistory) return
  if (!state.canvas) return
  if (state.nodes === prev.nodes && state.edges === prev.edges) return

  if (snapshotTimer) clearTimeout(snapshotTimer)
  snapshotTimer = setTimeout(() => {
    if (suspendHistory) return
    const snap = takeSnapshot(useStore.getState())
    if (!currentSnapshot) {
      currentSnapshot = snap
      return
    }
    if (snapshotKey(snap) === snapshotKey(currentSnapshot)) return
    const past = [...useStore.getState().historyPast, currentSnapshot].slice(-HISTORY_LIMIT)
    currentSnapshot = snap
    useStore.setState({ historyPast: past, historyFuture: [] })
  }, 450)
})
