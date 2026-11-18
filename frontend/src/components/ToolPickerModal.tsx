import { useState } from 'react'
import { useStore } from '../store'
import Modal from './Modal'

/**
 * 右键 tool 节点 →「套用内置工具」弹出这个列表。
 * 选一个就把对应的预览代码 + agent.py 原生代码写进该节点。
 */
export default function ToolPickerModal({
  nodeId,
  onClose,
}: {
  nodeId: string
  onClose: () => void
}) {
  const meta = useStore((s) => s.meta)
  const node = useStore((s) => s.nodes.find((n) => n.id === nodeId) || null)
  const applyToolPreset = useStore((s) => s.applyToolPreset)
  const presets = meta?.tool_presets || []
  const [query, setQuery] = useState('')

  const q = query.trim().toLowerCase()
  const filtered = q
    ? presets.filter((t) =>
        [
          t.label,
          t.description,
          t.summary,
          t.args,
          ...(t.params || []).map((p) => p.label),
        ]
          .filter(Boolean)
          .some((text) => String(text).toLowerCase().includes(q)),
      )
    : presets

  const pick = async (id: string) => {
    await applyToolPreset(nodeId, id)
    onClose()
  }

  return (
    <Modal
      title="套用内置工具"
      subtitle={
        node
          ? `给「${node.data.label}」选一个平台内置工具，代码会自动写进这个节点。`
          : '选一个平台内置工具，代码会自动写进这个节点。'
      }
      onClose={onClose}
      width={620}
      footer={<button onClick={onClose}>取消</button>}
    >
      <input
        autoFocus
        className="tool-pick-search"
        placeholder="搜索工具（名称 / 描述 / 参数）"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      <div className="tool-pick-list">
        {filtered.map((t) => (
          <div key={t.id} className="tool-pick-item" onClick={() => pick(t.id)}>
            <div className="row" style={{ gap: 8 }}>
              <b>{t.label}</b>
              <span className="dim small mono">{t.args}</span>
              <div style={{ flex: 1 }} />
              <span className="dim small">套用</span>
            </div>
            <div className="dim small" style={{ marginTop: 3, lineHeight: 1.6 }}>
              {t.summary || t.description}
            </div>
            {t.params?.length > 0 && (
              <div className="dim small" style={{ marginTop: 3 }}>
                可填参数：{t.params.map((p) => p.label).join('、')}
              </div>
            )}
          </div>
        ))}
        {filtered.length === 0 && (
          <div className="dim" style={{ padding: '14px 0', textAlign: 'center' }}>
            没有匹配的工具，换个关键词试试。
          </div>
        )}
      </div>
    </Modal>
  )
}
