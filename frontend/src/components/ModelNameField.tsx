import { useEffect, useId, useState } from 'react'
import { api } from '../api'
import { useStore } from '../store'

/**
 * 模型名输入框 + 「获取列表」按钮。
 * 填好 Base URL / API Key 后点一下，把服务商返回的模型拉下来填进下拉候选。
 * 输入框本身仍可自由手填（有些服务商不提供 /models 接口）。
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
  const [loading, setLoading] = useState(false)
  const listId = useId()

  // 换了服务商就把候选恢复成该服务商的预设
  useEffect(() => {
    setOptions(presets)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [presets.join('|')])

  const fetchModels = async (e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setLoading(true)
    try {
      const res = await api.listModels({
        base_url: baseUrl,
        api_key: (apiKey || '').trim() || undefined,
      })
      if (res.ok && res.models.length) {
        setOptions(res.models)
        if (!value && res.models.length === 1) onChange(res.models[0])
        toast(`${res.message}，点输入框可下拉选择`, 'ok')
      } else {
        toast(res.message || '没拿到模型列表，可以直接手填模型名', 'err')
      }
    } catch (err: any) {
      toast(`获取失败：${err.message || err}`, 'err')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="field">
      <span>{label}</span>
      <div className="row" style={{ gap: 6 }}>
        <input
          list={listId}
          value={value}
          placeholder={placeholder || presets[0] || '填 Base URL 和 Key 后可获取列表'}
          onChange={(e) => onChange(e.target.value)}
          style={{ flex: 1 }}
        />
        <button
          type="button"
          className="sm"
          onClick={fetchModels}
          disabled={loading}
          title="用当前 Base URL 和 API Key 拉取可用模型"
        >
          {loading ? <span className="spin" /> : '⟳'} 获取列表
        </button>
      </div>
      <datalist id={listId}>
        {options.map((m) => (
          <option key={m} value={m} />
        ))}
      </datalist>
      {options.length > 0 && (
        <div className="dim small" style={{ marginTop: 3 }}>
          候选 {options.length} 个，可下拉选择或直接输入
        </div>
      )}
    </div>
  )
}
