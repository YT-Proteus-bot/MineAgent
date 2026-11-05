import { useState } from 'react'
import { api } from '../api'
import { useStore } from '../store'
import Popover from './Popover'
import PromptModal from './PromptModal'

interface Props {
  onOpenUserCenter: () => void
  onOpenCanvasModel: () => void
}

export default function TopBar({ onOpenUserCenter, onOpenCanvasModel }: Props) {
  const canvas = useStore((s) => s.canvas)
  const canvases = useStore((s) => s.canvases)
  const meta = useStore((s) => s.meta)
  const dirty = useStore((s) => s.dirty)
  const saving = useStore((s) => s.saving)
  const running = useStore((s) => s.running)
  const lastSaved = useStore((s) => s.lastSaved)
  const loadCanvas = useStore((s) => s.loadCanvas)
  const save = useStore((s) => s.save)
  const run = useStore((s) => s.run)
  const runInput = useStore((s) => s.runInput)
  const setRunPanelOpen = useStore((s) => s.setRunPanelOpen)
  const renameCanvas = useStore((s) => s.renameCanvas)
  const deleteCanvas = useStore((s) => s.deleteCanvas)
  const changeFramework = useStore((s) => s.changeFramework)
  const createCanvas = useStore((s) => s.createCanvas)
  const toast = useStore((s) => s.toast)
  const report = useStore((s) => s.constraintReport)
  const setConstraintPanelOpen = useStore((s) => s.setConstraintPanelOpen)
  const historyPast = useStore((s) => s.historyPast)
  const historyFuture = useStore((s) => s.historyFuture)
  const undo = useStore((s) => s.undo)
  const redo = useStore((s) => s.redo)

  const [prompt, setPrompt] = useState<null | 'new' | 'rename'>(null)

  const currentFw = meta?.frameworks.find((f) => f.id === canvas?.framework)

  const handleRun = () => {
    setRunPanelOpen(true)
    if (!runInput.trim()) {
      toast('先在运行面板里填写任务输入', 'info')
      return
    }
    run(runInput)
  }

  const handleSwitchFramework = (id: string) => {
    if (!canvas || id === canvas.framework) return
    const fw = meta?.frameworks.find((f) => f.id === id)
    const ok = window.confirm(
      `切换框架会按「${fw?.label}」重新生成整套架构图，当前画布上的节点和连线会被替换（原项目目录会重建）。\n\n确定切换吗？`,
    )
    if (ok) changeFramework(id)
  }

  return (
    <header className="topbar">
      <div className="brand">
        <div className="mark">M</div>
        <div className="name">MineAgent</div>
        <div className="tag">agent canvas</div>
      </div>

      <Popover
        align="left"
        width={300}
        trigger={() => (
          <button>
            <span style={{ maxWidth: 190, overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {canvas?.name || '选择画布'}
            </span>
            <span className="dim small">▾</span>
          </button>
        )}
      >
        {(close) => (
          <>
            <div className="group-title">我的画布（{canvases.length}）</div>
            {canvases.map((c) => (
              <div
                key={c.id}
                className={`menu-item${c.id === canvas?.id ? ' active' : ''}`}
                onClick={() => {
                  loadCanvas(c.id)
                  close()
                }}
              >
                <span>▦</span>
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{c.name}</span>
                <span className="sub">{c.node_count} 节点</span>
              </div>
            ))}
            <div className="menu-sep" />
            <div
              className="menu-item"
              onClick={() => {
                setPrompt('new')
                close()
              }}
            >
              <span>＋</span> 新增画布
            </div>
            <div
              className="menu-item"
              onClick={() => {
                setPrompt('rename')
                close()
              }}
            >
              <span>✎</span> 重命名当前画布
            </div>
            <div
              className="menu-item"
              onClick={async () => {
                if (canvas) {
                  try {
                    const res = await api.openFolder(canvas.id)
                    toast(`已打开 ${res.path}`, 'ok')
                  } catch (err: any) {
                    toast(String(err.message || err), 'err')
                  }
                }
                close()
              }}
            >
              <span>📂</span> 打开项目目录
            </div>
            <div className="menu-sep" />
            <div
              className="menu-item"
              style={{ color: 'var(--err)' }}
              onClick={() => {
                if (canvas && window.confirm(`删除画布「${canvas.name}」？对应的项目文件夹也会被删除。`)) {
                  deleteCanvas()
                }
                close()
              }}
            >
              <span>🗑</span> 删除当前画布
            </div>
          </>
        )}
      </Popover>

      <button
        onClick={undo}
        disabled={historyPast.length === 0}
        title={`撤销（Ctrl+Z）${historyPast.length ? `，可退 ${historyPast.length} 步` : ''}`}
        className="icon"
      >
        ↶
      </button>
      <button
        onClick={redo}
        disabled={historyFuture.length === 0}
        title="重做（Ctrl+Shift+Z / Ctrl+Y）"
        className="icon"
      >
        ↷
      </button>

      <button
        onClick={() => save()}
        disabled={saving || !dirty}
        title="保存画布并把代码写入项目目录（Ctrl/Cmd+S）"
      >
        {saving ? <span className="spin" /> : <span>💾</span>}
        {dirty ? '保存' : lastSaved ? `已保存 ${lastSaved}` : '已保存'}
      </button>

      <button
        onClick={() => setConstraintPanelOpen(true)}
        title="检查编排约束（入口出口、连通性、自定义规则…）"
      >
        <span>⚠</span> 约束
        {report && report.counts.error > 0 && (
          <span className="badge err" style={{ padding: '0 5px' }}>
            {report.counts.error}
          </span>
        )}
        {report && report.counts.error === 0 && report.counts.warn > 0 && (
          <span className="badge warn" style={{ padding: '0 5px' }}>
            {report.counts.warn}
          </span>
        )}
      </button>

      <button className="primary" onClick={handleRun} disabled={running || !canvas}>
        {running ? <span className="spin" /> : <span>▶</span>}
        {running ? '运行中' : '运行'}
      </button>

      <div className="spacer" />

      {dirty && <span className="badge warn">未保存</span>}

      <Popover
        align="right"
        width={330}
        trigger={() => (
          <button title="选择 Agent 框架，切换后会重建架构图">
            <span
              style={{
                width: 8,
                height: 8,
                borderRadius: 4,
                background: currentFw?.color || '#6d8bff',
                display: 'inline-block',
              }}
            />
            {currentFw?.label || '选择框架'}
            <span className="dim small">▾</span>
          </button>
        )}
      >
        {(close) => (
          <>
            <div className="group-title">选择 Agent 框架</div>
            {(meta?.frameworks || []).map((f) => (
              <div
                key={f.id}
                className={`menu-item${f.id === canvas?.framework ? ' active' : ''}`}
                onClick={() => {
                  handleSwitchFramework(f.id)
                  close()
                }}
                title={f.description}
              >
                <span
                  style={{
                    width: 8,
                    height: 8,
                    borderRadius: 4,
                    background: f.color,
                    display: 'inline-block',
                    flex: 'none',
                  }}
                />
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{f.label}</span>
                <span className={`badge ${f.runnable ? 'ok' : ''}`}>{f.badge}</span>
              </div>
            ))}
          </>
        )}
      </Popover>

      <button onClick={onOpenCanvasModel} title="配置这个画布用的大模型与 key">
        <span>⚙</span> 模型
      </button>
      <button onClick={onOpenUserCenter} title="全局 API Key（编排用）">
        <span>👤</span> 用户中心
      </button>

      {prompt === 'new' && (
        <PromptModal
          title="新增画布"
          subtitle="每个画布对应一个独立的 Agent 项目文件夹，名字可以随时改。"
          defaultValue=""
          placeholder="例如：竞品调研智能体"
          confirmText="创建"
          onClose={() => setPrompt(null)}
          onConfirm={(name) => createCanvas(name || null, canvas?.framework || 'langchain')}
        />
      )}

      {prompt === 'rename' && canvas && (
        <PromptModal
          title="重命名画布"
          subtitle="项目文件夹会同步改名。"
          defaultValue={canvas.name}
          onClose={() => setPrompt(null)}
          onConfirm={(name) => renameCanvas(name)}
        />
      )}
    </header>
  )
}
