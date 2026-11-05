import { useEffect, useState } from 'react'
import { ReactFlowProvider } from '@xyflow/react'
import { useStore } from './store'
import TopBar from './components/TopBar'
import FlowCanvas from './components/FlowCanvas'
import AgentChatPanel from './components/AgentChatPanel'
import NodeInspector from './components/NodeInspector'
import RunPanel from './components/RunPanel'
import { CanvasModelModal, UserCenterModal } from './components/SettingsModals'

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

  const [userCenterOpen, setUserCenterOpen] = useState(false)
  const [canvasModelOpen, setCanvasModelOpen] = useState(false)

  useEffect(() => {
    init()
  }, [init])

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

      <div className="toasts">
        {toasts.map((t) => (
          <div key={t.id} className={`toast ${t.kind}`} onClick={() => dismissToast(t.id)}>
            {t.text}
          </div>
        ))}
      </div>

      {userCenterOpen && <UserCenterModal onClose={() => setUserCenterOpen(false)} />}
      {canvasModelOpen && <CanvasModelModal onClose={() => setCanvasModelOpen(false)} />}
    </div>
  )
}
