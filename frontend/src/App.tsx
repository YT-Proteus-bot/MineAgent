import { useEffect, useState } from 'react'
import { ReactFlowProvider } from '@xyflow/react'
import { useStore } from './store'
import TopBar from './components/TopBar'
import FlowCanvas from './components/FlowCanvas'
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

  const [userCenterOpen, setUserCenterOpen] = useState(false)
  const [canvasModelOpen, setCanvasModelOpen] = useState(false)

  useEffect(() => {
    init()
  }, [init])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
        e.preventDefault()
        if (dirty) save()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [dirty, save])

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
        <NodeInspector />
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
