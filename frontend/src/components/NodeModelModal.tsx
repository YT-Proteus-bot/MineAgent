import { useState } from 'react'
import { useStore } from '../store'
import Modal from './Modal'
import { PRESETS } from './SettingsModals'

/**
 * 给单个 agent 节点配置模型与 API Key。
 * Key 加密存在后端 agent_models 表，只以环境变量注入子进程，不会写进项目文件。
 */
export default function NodeModelModal({
  nodeId,
  onClose,
}: {
  nodeId: string
  onClose: () => void
}) {
  const node = useStore((s) => s.nodes.find((n) => n.id === nodeId))
  const setNodeModel = useStore((s) => s.setNodeModel)
  const clearNodeModel = useStore((s) => s.clearNodeModel)

  const saved = (node?.data.model || {}) as Record<string, any>
  const [form, setForm] = useState({
    provider: saved.provider || 'openai',
    base_url: saved.base_url || '',
    model: saved.model || '',
    temperature: saved.temperature ?? 0.3,
    max_tokens: saved.max_tokens ?? 2048,
  })
  const [key, setKey] = useState('')
  const [busy, setBusy] = useState(false)

  if (!node) return null

  const preset = PRESETS.find((p) => p.id === form.provider) || PRESETS[0]
  const hasKey = !!saved.has_key || !!saved.api_key_mask

  const save = async () => {
    setBusy(true)
    try {
      await setNodeModel(nodeId, {
        ...form,
        api_key: key ? key : undefined,
        inherit: false,
      })
      onClose()
    } finally {
      setBusy(false)
    }
  }

  const reset = async () => {
    setBusy(true)
    try {
      await clearNodeModel(nodeId)
      onClose()
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      title={`节点模型 · ${node.data.label}`}
      subtitle={`给这个 agent 单独指定模型与 key。不配置时跟随画布设置，再回退到用户中心的全局配置。`}
      onClose={onClose}
      footer={
        <>
          {hasKey && (
            <button onClick={reset} disabled={busy}>
              恢复跟随画布
            </button>
          )}
          <button onClick={onClose}>取消</button>
          <button className="primary" onClick={save} disabled={busy}>
            {busy ? <span className="spin" /> : null} 保存
          </button>
        </>
      }
    >
      <label className="field">
        <span>服务商</span>
        <select
          value={form.provider}
          onChange={(e) => {
            const p = PRESETS.find((x) => x.id === e.target.value)!
            setForm({
              ...form,
              provider: p.id,
              base_url: p.base || form.base_url,
              model: p.models[0] || form.model,
            })
          }}
        >
          {PRESETS.map((p) => (
            <option key={p.id} value={p.id}>
              {p.label}
            </option>
          ))}
        </select>
      </label>

      <label className="field">
        <span>Base URL</span>
        <input
          value={form.base_url}
          placeholder="留空则跟随画布 / 全局配置"
          onChange={(e) => setForm({ ...form, base_url: e.target.value })}
        />
      </label>

      <label className="field">
        <span>模型名</span>
        <input
          list="node-model-presets"
          value={form.model}
          placeholder={preset.models[0] || '留空则跟随画布配置'}
          onChange={(e) => setForm({ ...form, model: e.target.value })}
        />
        <datalist id="node-model-presets">
          {preset.models.map((m) => (
            <option key={m} value={m} />
          ))}
        </datalist>
      </label>

      <div className="row">
        <label className="field" style={{ flex: 1 }}>
          <span>Temperature</span>
          <input
            type="number"
            step="0.1"
            min="0"
            max="2"
            value={form.temperature}
            onChange={(e) => setForm({ ...form, temperature: Number(e.target.value) })}
          />
        </label>
        <label className="field" style={{ flex: 1 }}>
          <span>Max tokens</span>
          <input
            type="number"
            value={form.max_tokens}
            onChange={(e) => setForm({ ...form, max_tokens: Number(e.target.value) })}
          />
        </label>
      </div>

      <label className="field">
        <span>API Key</span>
        <input
          type="password"
          value={key}
          autoComplete="off"
          placeholder={
            hasKey ? `已保存 ${saved.api_key_mask}（留空不修改）` : '留空则用画布 / 全局 key'
          }
          onChange={(e) => setKey(e.target.value)}
        />
      </label>

      <div className="hint-box">
        这个 key 只属于当前节点，加密存在本机数据库里，运行时通过环境变量
        <code className="mono"> {saved.api_key_env || `MINEAGENT_KEY_${nodeId.toUpperCase()}`} </code>
        注入子进程，不会出现在
        <code className="mono"> agent.json </code>
        里。
      </div>
    </Modal>
  )
}
