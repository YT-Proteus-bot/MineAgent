import { useEffect, useState } from 'react'

/** 需要对接数据的节点：只有这些节点显示「数据接入」选择器 */
export const NEEDS_DATA = new Set([
  'dataset_reader',
  'db_write',
  'kv_store',
  'cache_lookup',
  'cache_write',
  'graph_query',
  'sql_query',
  'rag_retriever',
  'http_request',
])

interface Option {
  key: string
  label: string
  group: string
  value: Record<string, any>
}

interface Props {
  canvasId: string
  value: any
  onChange: (v: any) => void
}

function keyOf(v: any): string {
  if (!v || !v.kind) return ''
  if (v.kind === 'remote') return `remote:${v.logical || ''}`
  return `${v.kind}:${v.id || ''}`
}

export default function DataRefField({ canvasId, value, onChange }: Props) {
  const [options, setOptions] = useState<Option[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!canvasId) return
    let alive = true
    setLoading(true)
    fetch(`/api/canvases/${canvasId}/data/refs`)
      .then(async (r) => {
        const data = await r.json()
        if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`)
        if (!alive) return
        const list: Option[] = []
        for (const ds of data.datasets || []) {
          list.push({
            key: `dataset:${ds.id}`,
            group: '数据集（本画布）',
            label: `${ds.logical}${ds.kind === 'sql' ? '（SQL）' : ''}`,
            value: { kind: 'dataset', id: ds.id, logical: ds.logical },
          })
        }
        for (const src of data.sources || []) {
          list.push({
            key: `source:${src.id}`,
            group: '数据源（直连）',
            label: src.name || src.provider,
            value: { kind: 'source', id: src.id, name: src.name || src.provider },
          })
        }
        for (const rm of data.remote || []) {
          list.push({
            key: `remote:${rm.logical}`,
            group: '外部接入（HTTP 平台）',
            label: `${rm.logical} = ${rm.physical}${rm.mode === 'write' ? '（写）' : ''}`,
            value: { kind: 'remote', logical: rm.logical, physical: rm.physical || '' },
          })
        }
        setOptions(list)
      })
      .catch((e) => alive && setError(e.message || String(e)))
      .finally(() => alive && setLoading(false))
    return () => {
      alive = false
    }
  }, [canvasId])

  const current = keyOf(value)
  const groups = Array.from(new Set(options.map((o) => o.group)))

  return (
    <div className="field">
      <span>
        数据接入
        {loading && <span className="dim small">（读取中…）</span>}
      </span>
      <select
        value={current}
        onChange={(e) => {
          const hit = options.find((o) => o.key === e.target.value)
          onChange(hit ? hit.value : undefined)
        }}
      >
        <option value="">不指定（沿用节点自己的参数）</option>
        {groups.map((g) => (
          <optgroup key={g} label={g}>
            {options
              .filter((o) => o.group === g)
              .map((o) => (
                <option key={o.key} value={o.key}>
                  {o.label}
                </option>
              ))}
          </optgroup>
        ))}
      </select>
      {error ? (
        <div className="dim small" style={{ color: 'var(--warn, #b45309)' }}>
          读取数据中台失败：{error}
        </div>
      ) : (
        <div className="dim small">
          选了之后，生成代码会按这个引用取数；数据集走本画布，外部接入走 integrations.json
        </div>
      )}
    </div>
  )
}
