import { useEffect, useState } from 'react'
import { api } from '../api'
import { useStore } from '../store'
import Modal from './Modal'
import ModelNameField from './ModelNameField'
import CommunityModal from './CommunityModal'
import type { GlobalSettings, ModelConfig } from '../types'

/** 默认服务商是 DeepSeek，其余按需切换 */
export const DEFAULT_PROVIDER = { id: 'deepseek', base: 'https://api.deepseek.com/v1' }
export const DEFAULT_MODEL = 'deepseek-chat'

export const PRESETS = [
  {
    id: 'deepseek',
    label: 'DeepSeek',
    base: 'https://api.deepseek.com/v1',
    models: ['deepseek-chat', 'deepseek-reasoner', 'deepseek-flash'],
  },
  { id: 'openai', label: 'OpenAI', base: 'https://api.openai.com/v1', models: ['gpt-4o', 'gpt-4o-mini', 'gpt-4.1-mini'] },
  {
    id: 'qwen',
    label: '通义千问',
    base: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    models: ['qwen-plus', 'qwen-max', 'qwen-turbo'],
  },
  { id: 'zhipu', label: '智谱 GLM', base: 'https://open.bigmodel.cn/api/paas/v4', models: ['glm-4-plus', 'glm-4-flash'] },
  { id: 'moonshot', label: '月之暗面', base: 'https://api.moonshot.cn/v1', models: ['moonshot-v1-8k'] },
  { id: 'ollama', label: 'Ollama 本地', base: 'http://127.0.0.1:11434/v1', models: ['qwen2.5:7b'] },
  { id: 'custom', label: '自定义 / OpenAI 兼容', base: '', models: [] },
]

export function UserCenterModal({ onClose }: { onClose: () => void }) {
  const toast = useStore((s) => s.toast)
  const [form, setForm] = useState<GlobalSettings | null>(null)
  const [key, setKey] = useState('')
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState('')
  const [communityOpen, setCommunityOpen] = useState(false)
  const refreshCanvases = useStore((s) => s.refreshCanvases)
  const loadCanvas = useStore((s) => s.loadCanvas)

  useEffect(() => {
    api.getSettings().then(setForm).catch((e) => toast(String(e.message || e), 'err'))
  }, [toast])

  if (!form) return null

  const preset = PRESETS.find((p) => p.id === form.orchestrator_provider) || PRESETS[0]

  const save = async () => {
    try {
      const next = await api.putSettings({
        ...form,
        orchestrator_api_key: key ? key : undefined,
      })
      setForm(next)
      setKey('')
      toast('用户中心配置已保存', 'ok')
    } catch (e: any) {
      toast(`保存失败：${e.message || e}`, 'err')
    }
  }

  const test = async () => {
    setTesting(true)
    setTestResult('')
    try {
      const res = await api.testModel({
        api_key: key || undefined,
        base_url: form.orchestrator_base_url,
        model: form.orchestrator_model,
      })
      setTestResult(res.message)
    } catch (e: any) {
      setTestResult(String(e.message || e))
    } finally {
      setTesting(false)
    }
  }

  return (
    <Modal
      title="用户中心"
      subtitle="这里配置的是整个项目默认使用的大模型连接（编排与运行时的兜底配置）。单个画布可以在「模型」里单独覆盖。"
      onClose={onClose}
      footer={
        <>
          <button onClick={onClose}>取消</button>
          <button onClick={() => setCommunityOpen(true)} title="GitHub 登录、社区模板加载、上传配置">
            🌐 社区模板
          </button>
          <div style={{ flex: 1 }} />
          <button className="primary" onClick={save}>
            保存
          </button>
        </>
      }
    >
      <label className="field">
        <span>服务商</span>
        <select
          value={form.orchestrator_provider}
          onChange={(e) => {
            const p = PRESETS.find((x) => x.id === e.target.value)!
            setForm({
              ...form,
              orchestrator_provider: p.id,
              orchestrator_base_url: p.base || form.orchestrator_base_url,
              orchestrator_model: p.models[0] || form.orchestrator_model,
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
          value={form.orchestrator_base_url}
          placeholder={preset.base || 'https://api.deepseek.com/v1'}
          onChange={(e) => setForm({ ...form, orchestrator_base_url: e.target.value })}
        />
      </label>

      <ModelNameField
        value={form.orchestrator_model}
        onChange={(v) => setForm({ ...form, orchestrator_model: v })}
        presets={preset.models}
        baseUrl={form.orchestrator_base_url}
        apiKey={key}
        placeholder={preset.models[0] || DEFAULT_MODEL}
      />

      <label className="field">
        <span>API Key</span>
        <input
          type="password"
          value={key}
          autoComplete="off"
          placeholder={form.orchestrator_api_key_mask ? `已保存 ${form.orchestrator_api_key_mask}（留空不修改）` : 'sk-...'}
          onChange={(e) => setKey(e.target.value)}
        />
      </label>

      {testResult && (
        <div className="hint-box" style={{ borderColor: '#33456d', color: 'var(--text-dim)' }}>
          {testResult}
        </div>
      )}

      <div className="hint-box">
        key 会加密保存在本机 <code className="mono">backend/data/mineagent.db</code>，接口只回显掩码。
        完全离线时可以用项目自带 mock 服务：Base URL 填 <code className="mono">http://127.0.0.1:8012/v1</code>，
        模型填 <code className="mono">mock-model</code>，key 随便填。
      </div>

      {communityOpen && (
        <CommunityModal
          onClose={() => setCommunityOpen(false)}
          onLoaded={async (id) => {
            await refreshCanvases()
            await loadCanvas(id)
          }}
        />
      )}
    </Modal>
  )
}

export function CanvasModelModal({ onClose }: { onClose: () => void }) {
  const canvas = useStore((s) => s.canvas)
  const toast = useStore((s) => s.toast)
  const loadCanvas = useStore((s) => s.loadCanvas)
  const [form, setForm] = useState<ModelConfig | null>(canvas?.llm_config || null)
  const [key, setKey] = useState('')
  const [fallback, setFallback] = useState<GlobalSettings | null>(null)

  // 拉一次用户中心配置，好让用户看清「留空时实际会用哪一份」
  useEffect(() => {
    api
      .getSettings()
      .then(setFallback)
      .catch(() => setFallback(null))
  }, [])

  if (!canvas || !form) return null

  const preset = PRESETS.find((p) => p.id === form.provider) || PRESETS[0]
  const effectiveModel = form.model || fallback?.orchestrator_model || '未配置'
  const effectiveBase = form.base_url || fallback?.orchestrator_base_url || '未配置'

  const save = async () => {
    try {
      await api.setCanvasModel(canvas.id, { ...form, api_key: key || undefined })
      await loadCanvas(canvas.id)
      toast('画布模型配置已保存', 'ok')
      onClose()
    } catch (e: any) {
      toast(`保存失败：${e.message || e}`, 'err')
    }
  }

  return (
    <Modal
      title={`画布模型 · ${canvas.name}`}
      subtitle="这个画布运行时优先使用这里的配置；留空则回退到「用户中心」里的全局配置。"
      onClose={onClose}
      footer={
        <>
          <button onClick={onClose}>取消</button>
          <button className="primary" onClick={save}>
            保存
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
          placeholder="留空则使用用户中心的全局配置"
          onChange={(e) => setForm({ ...form, base_url: e.target.value })}
        />
      </label>
      <ModelNameField
        value={form.model}
        onChange={(v) => setForm({ ...form, model: v })}
        presets={preset.models}
        baseUrl={form.base_url}
        apiKey={key}
        placeholder="留空则使用全局配置"
      />
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
          placeholder={form.api_key_mask ? `已保存 ${form.api_key_mask}（留空不修改）` : '留空则使用全局 key'}
          onChange={(e) => setKey(e.target.value)}
        />
      </label>
      <div className="hint-box">
        <strong>这个画布实际生效：</strong> <code className="mono">{effectiveModel}</code> @{' '}
        <code className="mono">{effectiveBase}</code>
        <br />
        {form.model || form.base_url ? (
          <span style={{ color: 'var(--warn)' }}>↑ 用的是画布自己的配置（会覆盖用户中心）</span>
        ) : (
          <span style={{ color: 'var(--ok)' }}>↑ 画布没单独配，跟随「用户中心」</span>
        )}
        <br />
        运行时 key 通过环境变量注入子进程，不会明文写进项目文件夹。项目里也支持自己放
        <code className="mono"> .env</code> 做独立运行。
      </div>
    </Modal>
  )
}
