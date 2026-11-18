import { useEffect, useState } from 'react'

import Modal from './Modal'

interface VersionItem {
  version: string
  hash?: string
  generated_at?: string
  generated_at_local?: string
  archived_at?: string
  nodes?: number | null
  edges?: number | null
  bytes?: number | null
  is_current?: boolean
  source?: string
  rolled_back_from?: string
}

interface Props {
  canvasId: string
  canvasName?: string
  onClose: () => void
  /** 回滚成功后调用，让外层刷新画布（agent.py 已被替换） */
  onRolledBack?: () => void
}

export default function VersionHistoryModal({ canvasId, canvasName, onClose, onRolledBack }: Props) {
  const [versions, setVersions] = useState<VersionItem[]>([])
  const [changelog, setChangelog] = useState<string[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const load = async () => {
    setLoading(true)
    setError('')
    try {
      const resp = await fetch(`/api/canvases/${canvasId}/versions`)
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}))
        throw new Error(body.detail || `HTTP ${resp.status}`)
      }
      const data = await resp.json()
      setVersions(data.versions || [])
      setChangelog(data.changelog || [])
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [canvasId])

  const rollback = async (item: VersionItem) => {
    const target = item.generated_at ? item.generated_at.slice(0, 19).replace('T', ' ') : item.version
    if (!window.confirm(`回滚到 v${item.version}（${target}）？\n\n会把 agent.py 换成这一版，当前版本会自动留档，之后还能切回来。`)) {
      return
    }
    setBusy(item.version)
    setError('')
    setNotice('')
    try {
      const resp = await fetch(`/api/canvases/${canvasId}/versions/${item.version}/rollback`, {
        method: 'POST',
      })
      const body = await resp.json().catch(() => ({}))
      if (!resp.ok) throw new Error(body.detail || `HTTP ${resp.status}`)
      setNotice(body.changed === false ? `已经是 v${item.version}` : `已回滚到 v${item.version}`)
      await load()
      onRolledBack?.()
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc))
    } finally {
      setBusy('')
    }
  }

  return (
    <Modal
      title="版本历史"
      subtitle={canvasName ? `${canvasName} · 每次保存内容有变化就会留一版` : undefined}
      onClose={onClose}
      width={720}
      footer={
        <>
          <button onClick={() => void load()} disabled={loading || !!busy}>
            {loading ? <span className="spin" /> : <span>⟳</span>} 刷新
          </button>
          <button onClick={onClose}>关闭</button>
        </>
      }
    >
      {error && <div className="badge err" style={{ display: 'block', marginBottom: 10 }}>{error}</div>}
      {notice && <div className="badge ok" style={{ display: 'block', marginBottom: 10 }}>{notice}</div>}

      {loading && versions.length === 0 ? (
        <div className="sub">读取中…</div>
      ) : versions.length === 0 ? (
        <div className="sub">
          还没有版本记录。先在画布上点一次「保存」，生成器会写出 VERSION 并开始留档。
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {versions.map((item) => (
            <div
              key={item.version}
              className="row"
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 10,
                padding: '8px 10px',
                border: '1px solid var(--line, #e2e8f0)',
                borderRadius: 8,
                opacity: item.is_current ? 0.85 : 1,
              }}
            >
              <strong style={{ minWidth: 64 }}>v{item.version}</strong>
              {item.is_current && <span className="badge ok">当前</span>}
              {item.rolled_back_from && <span className="badge warn">回滚自 v{item.rolled_back_from}</span>}
              <span className="small" style={{ flex: 1 }}>
                {item.generated_at ? item.generated_at.slice(0, 19).replace('T', ' ') : item.archived_at || '—'}
                {typeof item.nodes === 'number' ? ` · ${item.nodes} 节点 / ${item.edges} 连线` : ''}
                {item.hash ? ` · ${item.hash}` : ''}
              </span>
              <button
                onClick={() => void rollback(item)}
                disabled={!!busy || item.is_current}
                title={item.is_current ? '已经是当前版本' : `把 agent.py 换成 v${item.version}`}
              >
                {busy === item.version ? <span className="spin" /> : '回滚到这一版'}
              </button>
            </div>
          ))}
        </div>
      )}

      {changelog.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <div className="sub" style={{ marginBottom: 6 }}>变更记录</div>
          <div
            className="small"
            style={{
              maxHeight: 180,
              overflow: 'auto',
              whiteSpace: 'pre-wrap',
              fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
              lineHeight: 1.6,
            }}
          >
            {changelog.join('\n')}
          </div>
        </div>
      )}
    </Modal>
  )
}
