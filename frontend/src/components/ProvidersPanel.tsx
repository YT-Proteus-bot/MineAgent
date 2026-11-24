import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import { useStore } from '../store'
import type {
  CatalogItem,
  CatalogKind,
  ProviderCatalog,
  ProviderField,
  ProviderKind,
  ProviderRecord,
  ProviderTestResult,
} from '../types'

/** 新建 / 编辑时的草稿 */
interface Draft {
  id?: string
  provider: string
  name: string
  config: Record<string, any>
  secret: Record<string, string>
  is_default: boolean
}

function defaultConfig(item: CatalogItem): Record<string, any> {
  const cfg: Record<string, any> = {}
  if (item.base_url) cfg.base_url = item.base_url
  for (const f of item.fields) {
    if (f.secret) continue
    if (f.default !== undefined && f.default !== null && f.default !== '') {
      cfg[f.key] = f.default
    } else if (!(f.key in cfg)) {
      cfg[f.key] = ''
    }
  }
  const first = item.models?.[0]
  if (first && !cfg.model) {
    cfg.model = first.id
    if (first.dim) cfg.dim = first.dim
  }
  return cfg
}

/**
 * 向量检索模型 / 重排模型 / 向量库 / 数据源 的统一配置面板。
 *
 * 字段完全由后端的 catalog 驱动：加一家厂商只改后端清单，
 * 这里不需要动；未实现（planned）的条目在下拉里禁用。
 * title / desc 只在个别入口覆盖标题文案（比如画布配置里叫「向量检索模型」），
 * 分类本身仍是 catalog 里的 embedding。
 */
export function ProvidersPanel({ kind, canvasId, title, desc }: {
  kind: ProviderKind
  canvasId: string
  /** 覆盖面板标题；留空用 catalog 里的分类名 */
  title?: string
  /** 覆盖面板副标题；留空用 catalog 里的说明 */
  desc?: string
}) {
  const toast = useStore((s) => s.toast)
  const [catalog, setCatalog] = useState<ProviderCatalog | null>(null)
  const [records, setRecords] = useState<ProviderRecord[]>([])
  const [draft, setDraft] = useState<Draft | null>(null)
  const [testing, setTesting] = useState(false)
  const [result, setResult] = useState<ProviderTestResult | null>(null)
  const [saving, setSaving] = useState(false)

  const kindMeta: CatalogKind | undefined = useMemo(
    () => catalog?.kinds.find((k) => k.id === kind),
    [catalog, kind],
  )

  const load = useCallback(async () => {
    try {
      const [cat, list] = await Promise.all([
        catalog ? Promise.resolve(catalog) : api.providerCatalog(),
        api.listProviders({ kind, canvas_id: canvasId }),
      ])
      setCatalog(cat)
      setRecords(list)
    } catch (e: any) {
      toast(`加载失败：${e.message || e}`, 'err')
    }
  }, [kind, canvasId, catalog, toast])

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind, canvasId])

  const findItem = useCallback(
    (id: string) => kindMeta?.items.find((i) => i.id === id),
    [kindMeta],
  )

  const startCreate = () => {
    const first = kindMeta?.items.find((i) => i.status === 'ready') || kindMeta?.items[0]
    if (!first) return
    setResult(null)
    setDraft({
      provider: first.id,
      name: first.label,
      config: defaultConfig(first),
      secret: {},
      is_default: records.length === 0,
    })
  }

  const startEdit = (rec: ProviderRecord) => {
    setResult(null)
    setDraft({
      id: rec.id,
      provider: rec.provider,
      name: rec.name,
      config: { ...rec.config },
      secret: {},
      is_default: rec.is_default,
    })
  }

  const pickProvider = (id: string) => {
    const item = findItem(id)
    if (!item || !draft) return
    setResult(null)
    setDraft({
      ...draft,
      provider: id,
      name: draft.id ? draft.name : item.label,
      config: defaultConfig(item),
      secret: {},
    })
  }

  const setField = (key: string, value: any, secret = false) => {
    if (!draft) return
    if (secret) setDraft({ ...draft, secret: { ...draft.secret, [key]: value } })
    else setDraft({ ...draft, config: { ...draft.config, [key]: value } })
  }

  const currentItem = draft ? findItem(draft.provider) : undefined

  const validate = (): string => {
    if (!draft || !currentItem) return '请选择具体厂商/库'
    for (const f of currentItem.fields) {
      // 编辑已存记录时，密钥留空表示沿用原值
      if (f.secret && draft.id) continue
      if (!f.required) continue
      const value = f.secret ? draft.secret[f.key] : draft.config[f.key]
      if (value === undefined || value === null || String(value).trim() === '') {
        return `请填写「${f.label}」`
      }
    }
    return ''
  }

  const test = async () => {
    if (!draft || !currentItem) return
    const problem = validate()
    if (problem) {
      toast(problem, 'err')
      return
    }
    setTesting(true)
    setResult(null)
    try {
      const payload: any = {
        kind,
        provider: draft.provider,
        config: draft.config,
        secret: draft.secret,
      }
      if (draft.id) payload.id = draft.id
      setResult(await api.testProvider(payload))
    } catch (e: any) {
      setResult({ ok: false, message: String(e.message || e) })
    } finally {
      setTesting(false)
    }
  }

  const save = async () => {
    if (!draft || !currentItem) return
    const problem = validate()
    if (problem) {
      toast(problem, 'err')
      return
    }
    setSaving(true)
    try {
      const payload: any = {
        kind,
        provider: draft.provider,
        name: draft.name || currentItem.label,
        config: draft.config,
        is_default: draft.is_default,
        canvas_id: canvasId,
      }
      if (Object.keys(draft.secret).length) payload.secret = draft.secret
      if (draft.id) await api.updateProvider(draft.id, payload)
      else await api.createProvider(payload)
      toast(draft.id ? '已更新' : '已创建', 'ok')
      setDraft(null)
      setResult(null)
      await load()
    } catch (e: any) {
      toast(`保存失败：${e.message || e}`, 'err')
    } finally {
      setSaving(false)
    }
  }

  const remove = async (rec: ProviderRecord) => {
    if (!window.confirm(`删除「${rec.name}」？引用它的画布会回退到内置实现。`)) return
    try {
      await api.deleteProvider(rec.id)
      toast('已删除', 'ok')
      await load()
    } catch (e: any) {
      toast(`删除失败：${e.message || e}`, 'err')
    }
  }

  const makeDefault = async (rec: ProviderRecord) => {
    try {
      await api.setProviderDefault(rec.id)
      await load()
    } catch (e: any) {
      toast(`设置失败：${e.message || e}`, 'err')
    }
  }

  const renderField = (f: ProviderField) => {
    if (!draft) return null
    const secret = f.secret
    const value = secret
      ? draft.secret[f.key] ?? ''
      : draft.config[f.key] ?? f.default ?? ''
    const placeholder = secret
      ? draft.id
        ? '留空不修改'
        : f.placeholder || '填写密钥'
      : f.placeholder

    if (f.kind === 'select' && f.options?.length) {
      return (
        <label className="field" key={f.key}>
          <span>{f.label}{f.required ? ' *' : ''}</span>
          <select value={String(value)} onChange={(e) => setField(f.key, e.target.value, secret)}>
            {f.options.map((opt) => (
              <option key={opt} value={opt}>{opt}</option>
            ))}
          </select>
          {f.help && <small className="hint-text">{f.help}</small>}
        </label>
      )
    }

    return (
      <label className="field" key={f.key}>
        <span>{f.label}{f.required ? ' *' : ''}</span>
        <input
          type={secret ? 'password' : f.kind === 'number' ? 'number' : 'text'}
          value={value}
          autoComplete="off"
          placeholder={placeholder}
          onChange={(e) =>
            setField(f.key, f.kind === 'number' ? e.target.value : e.target.value, secret)
          }
        />
        {f.help && <small className="hint-text">{f.help}</small>}
      </label>
    )
  }

  const groupedItems = useMemo(() => {
    const groups = catalog?.groups || {}
    const order = Object.keys(groups)
    const map = new Map<string, CatalogItem[]>()
    for (const item of kindMeta?.items || []) {
      const list = map.get(item.group) || []
      list.push(item)
      map.set(item.group, list)
    }
    return [...map.entries()].sort(
      (a, b) => order.indexOf(a[0]) - order.indexOf(b[0]),
    )
  }, [catalog, kindMeta])

  return (
    <div className="providers-panel">
      <div className="providers-head">
        <div>
          <div className="providers-title">{title || kindMeta?.label || kind}</div>
          <div className="hint-text">{desc || kindMeta?.desc}</div>
        </div>
        <button className="primary" onClick={startCreate} disabled={!kindMeta}>
          + 新建
        </button>
      </div>

      {!draft && (
        <div className="providers-list">
          {records.length === 0 && (
            <div className="hint-box">
              还没有配置。新建一个之后，画布就会用它；不配的时候向量相关节点会回退到内置 SQLite 实现。
            </div>
          )}
          {records.map((rec) => (
            <div className="provider-card" key={rec.id}>
              <div className="provider-card-main">
                <div>
                  <strong>{rec.name}</strong>
                  <span className="provider-badge">{rec.label || rec.provider}</span>
                  {rec.is_default && <span className="provider-badge ok">默认</span>}
                  {rec.status === 'planned' && (
                    <span className="provider-badge warn">即将支持</span>
                  )}
                </div>
                <div className="hint-text">
                  {String(rec.config.collection || rec.config.index || rec.config.database || '')}
                  {Object.entries(rec.secret_mask || {}).map(([k, v]) => (
                    <span key={k}> · {k} {v}</span>
                  ))}
                </div>
              </div>
              <div className="provider-card-actions">
                {!rec.is_default && (
                  <button onClick={() => makeDefault(rec)}>设为默认</button>
                )}
                <button onClick={() => startEdit(rec)}>编辑</button>
                <button onClick={() => remove(rec)}>删除</button>
              </div>
            </div>
          ))}
        </div>
      )}

      {draft && (
        <div className="provider-form">
          <label className="field">
            <span>厂商 / 类型</span>
            <select value={draft.provider} onChange={(e) => pickProvider(e.target.value)}>
              {groupedItems.map(([group, items]) => (
                <optgroup key={group} label={catalog?.groups?.[group] || group}>
                  {items.map((item) => (
                    <option
                      key={item.id}
                      value={item.id}
                      disabled={item.status === 'planned'}
                    >
                      {item.label}
                      {item.status === 'planned' ? '（即将支持）' : ''}
                    </option>
                  ))}
                </optgroup>
              ))}
            </select>
          </label>

          <label className="field">
            <span>名称</span>
            <input
              value={draft.name}
              placeholder={currentItem?.label || '给这套配置起个名字'}
              onChange={(e) => setDraft({ ...draft, name: e.target.value })}
            />
          </label>

          {(currentItem?.fields || []).map(renderField)}

          {currentItem?.models?.length ? (
            <label className="field">
              <span>常用模型（点了会填进模型名）</span>
              <select
                value={String(draft.config.model || '')}
                onChange={(e) => {
                  const picked = currentItem.models.find((m) => m.id === e.target.value)
                  setDraft({
                    ...draft,
                    config: {
                      ...draft.config,
                      model: e.target.value,
                      ...(picked?.dim ? { dim: picked.dim } : {}),
                    },
                  })
                }}
              >
                <option value="">— 保持当前 —</option>
                {currentItem.models.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.id}{m.dim ? `（${m.dim} 维）` : ''}
                  </option>
                ))}
              </select>
            </label>
          ) : null}

          {currentItem?.pip && (
            <div className="hint-box">
              需要先安装依赖：<code className="mono">pip install {currentItem.pip}</code>
              （没装时节点会给出同样的安装提示，不会把整条流程跑崩）
            </div>
          )}

          {currentItem?.help && <div className="hint-box">{currentItem.help}</div>}

          <label className="field checkbox-field">
            <span>
              <input
                type="checkbox"
                checked={draft.is_default}
                onChange={(e) => setDraft({ ...draft, is_default: e.target.checked })}
              />{' '}
              设为默认（同一作用域内只有一个）
            </span>
          </label>

          {result && (
            <div
              className="hint-box"
              style={{ borderColor: result.ok ? 'var(--ok)' : 'var(--err)' }}
            >
              <strong>{result.ok ? '连接成功' : '连接失败'}</strong>：{result.message}
              {result.hint && <div className="hint-text">{result.hint}</div>}
              {result.tables?.length ? (
                <div className="hint-text">可用表/索引：{result.tables.join('、')}</div>
              ) : null}
            </div>
          )}

          <div className="row provider-form-actions">
            <button onClick={test} disabled={testing}>
              {testing ? '测试中…' : '测试连接'}
            </button>
            <div style={{ flex: 1 }} />
            <button onClick={() => { setDraft(null); setResult(null) }}>取消</button>
            <button className="primary" onClick={save} disabled={saving}>
              {saving ? '保存中…' : '保存'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
