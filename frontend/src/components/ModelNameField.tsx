import { useEffect, useId, useRef, useState } from 'react'
import { api } from '../api'
import { useStore } from '../store'

/**
 * 模型名选择器：
 * - 输入框可以自由手填；
 * - 「获取列表」按当前 Base URL / API Key 拉服务商模型，填进下拉；
 * - 下拉是自绘面板（原生 datalist 在部分浏览器里点不开）；
 * - 「测试连接」用当前配置发一次最小请求验证可用性。
 */
export default function ModelNameField({
  label = '模型名',
  value,
  onChange,
  presets = [],
  baseUrl,
  apiKey,
  placeholder,
}: {
  label?: string
  value: string
  onChange: (v: string) => void
  presets?: string[]
  baseUrl: string
  apiKey?: string
  placeholder?: string
}) {
  const toast = useStore((s) => s.toast)
  const [options, setOptions] = useState<string[]>(presets)
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [testing, setTesting] = useState(false)
  const boxRef = useRef<HTMLDivElement>(null)
  const listId = useId()

  useEffect(() => {
    setOptions(presets)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [presets.join('|')])

  // 点外面收起
  useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false)
    }
    const onEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    document.addEventListener('keydown', onEsc)
    return () => {
      document.removeEventListener('mousedown', onDoc)
      document.removeEventListener('keydown', onEsc)
    }
  }, [open])

  const fetchModels = async () => {
    setLoading(true)
    try {
      const res = await api.listModels({
        base_url: baseUrl,
        api_key: (apiKey || '').trim() || undefined,
      })
      if (res.ok && res.models.length) {
        setOptions(res.models)
        setOpen(true)
        if (!value && res.models.length === 1) onChange(res.models[0])
        toast(`${res.message}，已展开列表`, 'ok')
      } else {
        toast(res.message || '没拿到模型列表，可以直接手填模型名', 'err')
      }
    } catch (err: any) {
      toast(`获取失败：${err.message || err}`, 'err')
    } finally {
      setLoading(false)
    }
  }

  const testConnection = async () => {
    setTesting(true)
    try {
      const res = await api.testModel({
        base_url: baseUrl,
        api_key: (apiKey || '').trim() || undefined,
        model: value || undefined,
      })
      toast(res.message, res.ok ? 'ok' : 'err')
    } catch (err: any) {
      toast(`测试失败：${err.message || err}`, 'err')
    } finally {
      setTesting(false)
    }
  }

  return (
    <div className="field">
      <span>{label}</span>
      <div className="model-picker" ref={boxRef}>
        <input
          id={listId}
          value={value}
          placeholder={placeholder || presets[0] || '填 Base URL 和 Key 后可获取列表'}
          onChange={(e) => onChange(e.target.value)}
          onFocus={() => options.length > 0 && setOpen(true)}
        />
        <button
          type="button"
          className="mp-btn mp-arrow"
          onClick={() => setOpen((v) => !v)}
          disabled={options.length === 0}
          title={options.length ? `展开 ${options.length} 个候选模型` : '先点「获取列表」'}
        >
          ▾
        </button>
        <button
          type="button"
          className="mp-btn"
          onClick={fetchModels}
          disabled={loading}
          title="用当前 Base URL 和 API Key 拉取可用模型"
        >
          {loading ? <span className="spin" /> : '⟳'} 获取
        </button>
        <button
          type="button"
          className="mp-btn"
          onClick={testConnection}
          disabled={testing}
          title="用当前配置发一次最小请求，验证地址 / Key / 模型是否可用"
        >
          {testing ? <span className="spin" /> : '⚡'} 测试
        </button>

        {open && options.length > 0 && (
          <div className="mp-menu">
            {options.map((m) => (
              <div
                key={m}
                className={`mp-item${m === value ? ' active' : ''}`}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => {
                  onChange(m)
                  setOpen(false)
                }}
              >
                {m}
              </div>
            ))}
          </div>
        )}
      </div>
      {options.length > 0 && (
        <div className="dim small" style={{ marginTop: 3 }}>
          候选 {options.length} 个，点 ▾ 展开或直接输入
        </div>
      )}
    </div>
  )
}
