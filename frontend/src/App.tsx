import { useEffect, useState } from 'react'
import { ReactFlowProvider } from '@xyflow/react'
import { useStore, type UploadPayload } from './store'
import TopBar from './components/TopBar'
import FlowCanvas from './components/FlowCanvas'
import AgentChatPanel from './components/AgentChatPanel'
import NodeInspector from './components/NodeInspector'
import RunPanel from './components/RunPanel'
import UploadJobsPanel from './components/UploadJobsPanel'
import ConflictDialog, { type ConflictChoice } from './components/ConflictDialog'
import { CanvasModelModal, UserCenterModal } from './components/SettingsModals'
import KnowledgeModal from './components/KnowledgeModal'
import EvalModal from './components/EvalModal'
import DataHubModal from './components/DataHubModal'
import { api } from './api'

export default function App() {
  const init = useStore((s) => s.init)
  const loading = useStore((s) => s.loading)
  const toasts = useStore((s) => s.toasts)
  const dismissToast = useStore((s) => s.dismissToast)
  const save = useStore((s) => s.save)
  const dirty = useStore((s) => s.dirty)
  const rightTab = useStore((s) => s.rightTab)
  const setRightTab = useStore((s) => s.setRightTab)
  const undo = useStore((s) => s.undo)
  const redo = useStore((s) => s.redo)
  const toast = useStore((s) => s.toast)

  const [userCenterOpen, setUserCenterOpen] = useState(false)
  const [canvasModelOpen, setCanvasModelOpen] = useState(false)
  const [knowledgeOpen, setKnowledgeOpen] = useState(false)
  const [evalOpen, setEvalOpen] = useState(false)
  const [dataHubOpen, setDataHubOpen] = useState(false)

  const syncConflict = useStore((s) => s.syncConflict)
  const setSyncConflict = useStore((s) => s.setSyncConflict)
  const pendingUpload = useStore((s) => s.pendingUpload)
  const startUpload = useStore((s) => s.startUpload)
  const loadCanvas = useStore((s) => s.loadCanvas)
  const refreshCanvases = useStore((s) => s.refreshCanvases)

  /** 冲突对话框的选择：不自动合并，按用户选的动作执行 */
  const onConflictChoose = async (choice: ConflictChoice) => {
    const info = syncConflict
    if (!info || choice === 'cancel') {
      setSyncConflict(null)
      return
    }

    if (info.kind === 'remote-changed') {
      if (choice === 'overwrite' && pendingUpload) {
        startUpload({
          ...(pendingUpload as UploadPayload),
          force: true,
          base_rev: info.base_rev,
          remote_slug: info.remote_slug,
        })
        toast('已按你的选择覆盖推送', 'info')
      } else if (choice === 'pull-first') {
        toast('请到用户中心 → 公共模板里拉取最新版，合并后再推送', 'info')
      }
      setSyncConflict(null)
      return
    }

    // local-changed：拉取会覆盖本地
    if (choice === 'overwrite' && info.remote_slug) {
      try {
        const res = await api.loadCommunityTemplate(info.remote_slug, {
          mode: 'update',
          canvasId: info.canvas_id,
          force: true,
        })
        await loadCanvas(res.canvas.id)
        await refreshCanvases()
        toast('已用远端版本覆盖本地画布', 'ok')
      } catch (e: any) {
        toast(`覆盖失败：${e.message || e}`, 'err')
      }
    } else if (choice === 'save-as-new' && info.remote_slug) {
      try {
        // 先把本地当前内容另存成一张新画布，再更新原画布
        const src = await api.getCanvas(info.canvas_id!)
        const copy = await api.createCanvas(`${src.name}（本地副本）`, src.framework)
        await api.saveCanvas(copy.id, {
          nodes: src.graph.nodes,
          edges: src.graph.edges,
          viewport: src.graph.viewport,
          background: src.background,
        })
        const res = await api.loadCommunityTemplate(info.remote_slug, {
          mode: 'update',
          canvasId: info.canvas_id,
          force: true,
        })
        await loadCanvas(res.canvas.id)
        await refreshCanvases()
        toast('本地修改已另存为新画布，原画布已更新为远端版本', 'ok')
      } catch (e: any) {
        toast(`处理失败：${e.message || e}`, 'err')
      }
    }
    setSyncConflict(null)
  }

  useEffect(() => {
    init()
  }, [init])

  // GitHub OAuth 回调：?github=connected / ?github=error&reason=...
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const status = params.get('github')
    if (!status) return
    const reason = params.get('reason')
    if (status === 'connected') toast('GitHub 已连接', 'ok')
    else toast(`GitHub 连接失败${reason ? `（${reason}）` : ''}`, 'err')
    params.delete('github')
    params.delete('reason')
    const query = params.toString()
    window.history.replaceState(
      {},
      '',
      `${window.location.pathname}${query ? `?${query}` : ''}`,
    )
  }, [toast])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.ctrlKey || e.metaKey)) return
      const key = e.key.toLowerCase()
      const el = e.target as HTMLElement | null
      const typing =
        !!el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable)

      if (key === 's') {
        e.preventDefault()
        if (dirty) save()
        return
      }
      // 在输入框里按 Ctrl+Z 交给浏览器自己处理（撤销打字），不动画布
      if (typing) return
      if (key === 'z') {
        e.preventDefault()
        if (e.shiftKey) redo()
        else undo()
      } else if (key === 'y') {
        e.preventDefault()
        redo()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [dirty, save, undo, redo])

  useEffect(() => {
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      if (dirty) {
        e.preventDefault()
        e.returnValue = ''
      }
    }
    window.addEventListener('beforeunload', onBeforeUnload)
    return () => window.removeEventListener('beforeunload', onBeforeUnload)
  }, [dirty])

  if (loading) {
    return (
      <div className="app" style={{ display: 'grid', placeItems: 'center' }}>
        <div className="col" style={{ alignItems: 'center', gap: 12 }}>
          <span className="spin" style={{ width: 22, height: 22, borderWidth: 3 }} />
          <span className="dim">正在加载 MineAgent…</span>
        </div>
      </div>
    )
  }

  return (
    <div className="app">
      <TopBar
        onOpenUserCenter={() => setUserCenterOpen(true)}
        onOpenCanvasModel={() => setCanvasModelOpen(true)}
      onOpenKnowledge={() => setKnowledgeOpen(true)}
      onOpenEval={() => setEvalOpen(true)}
      onOpenDataHub={() => setDataHubOpen(true)}
      />
      <div className="main">
        <ReactFlowProvider>
          <FlowCanvas />
        </ReactFlowProvider>
        <aside className="right-pane">
          <div className="pane-tabs">
            <div
              className={`pane-tab${rightTab === 'assistant' ? ' active' : ''}`}
              onClick={() => setRightTab('assistant')}
            >
              ✦ AI 助手
            </div>
            <div
              className={`pane-tab${rightTab === 'node' ? ' active' : ''}`}
              onClick={() => setRightTab('node')}
            >
              节点详情
            </div>
          </div>
          <div className="pane-content">
            {rightTab === 'assistant' ? <AgentChatPanel /> : <NodeInspector />}
          </div>
        </aside>
      </div>
      <RunPanel />
      <UploadJobsPanel />

      <div className="toasts">
        {toasts.map((t) => (
          <div key={t.id} className={`toast ${t.kind}`} onClick={() => dismissToast(t.id)}>
            {t.text}
          </div>
        ))}
      </div>

      {userCenterOpen && <UserCenterModal onClose={() => setUserCenterOpen(false)} />}
      {canvasModelOpen && <CanvasModelModal onClose={() => setCanvasModelOpen(false)} />}
      {knowledgeOpen && <KnowledgeModal onClose={() => setKnowledgeOpen(false)} />}
      {evalOpen && <EvalModal onClose={() => setEvalOpen(false)} />}
      {dataHubOpen && <DataHubModal onClose={() => setDataHubOpen(false)} />}
      {syncConflict && (
        <ConflictDialog
          info={syncConflict}
          onChoose={onConflictChoose}
          onClose={() => setSyncConflict(null)}
        />
      )}
    </div>
  )
}
