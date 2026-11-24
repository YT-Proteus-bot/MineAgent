import { useCallback, useEffect, useState } from 'react'

import { useStore } from '../store'
import { type ServiceConfig } from '../types'
import { datasetsText, mergeService, parseDatasets } from '../serviceConfig'
import { ProvidersPanel } from './ProvidersPanel'

/**
 * 数据中台：画布级数据层的唯一入口。
 *
 * 数据源（连接 + 密钥）在「数据源」页，复用 providers(kind='data')；
 * 向量库在「向量库」页，复用 providers(kind='vector')——它本质也是「数据的存放处」，
 * 所以从「画布配置」挪到这里，模型相关的（对话/向量模型/重排）才留在画布配置；
 * 数据集（逻辑名 → 表 / SQL）在「数据集」页，节点里用 ctx.data.query("orders") 取数。
 */
type Tab = 'sources' | 'vector' | 'datasets' | 'service'

interface Source {
  id: string
  provider: string
  name: string
  scope: string
}

interface Dataset {
  id: string
  logical: string
  kind: string
  mode: string
  description: string
  source_id: string
  spec: Record<string, any>
  columns: string[]
}

interface Preview {
  columns: string[]
  rows: Record<string, any>[]
  statement: string
  row_count: number
}

const EMPTY = { logical: '', source_id: '', kind: 'table', table: '', sql: '', description: '' }

export default function DataHubModal({ onClose }: { onClose: () => void }) {
  const canvas = useStore((s) => s.canvas)
  const toast = useStore((s) => s.toast)
  const setServiceConfig = useStore((s) => s.setServiceConfig)
  const saveCanvas = useStore((s) => s.save)
  const [tab, setTab] = useState<Tab>('sources')
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [sources, setSources] = useState<Source[]>([])
  const [tables, setTables] = useState<string[]>([])
  const [form, setForm] = useState({ ...EMPTY })
  const [preview, setPreview] = useState<{ name: string; data: Preview } | null>(null)
  const [busy, setBusy] = useState('')
  const [svc, setSvc] = useState<ServiceConfig>(() => mergeService((canvas?.graph as any)?.service))
  const [savingSvc, setSavingSvc] = useState(false)

  useEffect(() => {
    setSvc(mergeService((canvas?.graph as any)?.service))
  }, [canvas?.id])

  const cid = canvas?.id || ''

  const load = useCallback(async () => {
    if (!cid) return
    try {
      const r = await fetch(`/api/canvases/${cid}/data`)
      const data = await r.json()
      if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`)
      setDatasets(data.datasets || [])
      setSources(data.sources || [])
      setForm((f) => ({ ...f, source_id: f.source_id || data.sources?.[0]?.id || '' }))
    } catch (e: any) {
      toast(`读取数据集失败：${e.message || e}`, 'err')
    }
  }, [cid, toast])

  useEffect(() => {
    if (tab === 'datasets') void load()
  }, [tab, load])

  const loadTables = async (sourceId: string) => {
    if (!cid || !sourceId) return
    try {
      const r = await fetch(`/api/canvases/${cid}/data/sources/${sourceId}/tables`)
      const data = await r.json()
      setTables(r.ok ? data.tables || [] : [])
      if (!r.ok) toast(String(data.detail || '读取表清单失败'), 'err')
    } catch {
      setTables([])
    }
  }

  const create = async () => {
    if (!cid) return
    if (!form.logical.trim()) return toast('给数据集起个名字（节点里就按这个名字取数）', 'err')
    if (!form.source_id) return toast('先选一个数据源', 'err')
    if (form.kind === 'table' && !form.table.trim()) return toast('选一张表', 'err')
    if (form.kind === 'sql' && !form.sql.trim()) return toast('写一条查询语句', 'err')
    setBusy('create')
    try {
      const body = {
        logical: form.logical.trim(),
        source_id: form.source_id,
        kind: form.kind,
        spec: form.kind === 'table' ? { table: form.table.trim() } : { sql: form.sql.trim() },
        description: form.description.trim(),
        mode: 'read',
      }
      const r = await fetch(`/api/canvases/${cid}/data`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const data = await r.json()
      if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`)
      toast(`数据集「${data.logical}」已创建`, 'ok')
      setForm({ ...EMPTY, source_id: form.source_id })
      await load()
    } catch (e: any) {
      toast(`创建失败：${e.message || e}`, 'err')
    } finally {
      setBusy('')
    }
  }

  const remove = async (ds: Dataset) => {
    if (!cid) return
    if (!window.confirm(`删除数据集「${ds.logical}」？节点里引用它的地方会失效。`)) return
    setBusy(ds.id)
    try {
      const r = await fetch(`/api/canvases/${cid}/data/${ds.id}`, { method: 'DELETE' })
      if (!r.ok) throw new Error((await r.json()).detail || `HTTP ${r.status}`)
      if (preview?.name === ds.logical) setPreview(null)
      await load()
    } catch (e: any) {
      toast(`删除失败：${e.message || e}`, 'err')
    } finally {
      setBusy('')
    }
  }

  const openPreview = async (ds: Dataset) => {
    if (!cid) return
    setBusy(ds.id)
    try {
      const r = await fetch(`/api/canvases/${cid}/data/datasets/${ds.id}/preview?limit=20`)
      const data = await r.json()
      if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`)
      setPreview({ name: ds.logical, data })
    } catch (e: any) {
      toast(`预览失败：${e.message || e}`, 'err')
    } finally {
      setBusy('')
    }
  }

  const patchSvc = (key: string, value: any) =>
    setSvc((f) => ({ ...f, data: { ...f.data, [key]: value } }))

  const saveService = async () => {
    setSavingSvc(true)
    try {
      setServiceConfig(svc)
      const ok = await saveCanvas()
      toast(ok ? '外部接入配置已保存（生成物会带上 integrations.json）' : '保存失败', ok ? 'ok' : 'err')
    } finally {
      setSavingSvc(false)
    }
  }

  const sourceName = (id: string) => sources.find((s) => s.id === id)?.name || sources.find((s) => s.id === id)?.provider || '—'

  return (
    <div className="modal-mask" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div
        className="modal"
        style={{
          width: 'min(1120px, 94vw)',
          height: 'min(800px, 90vh)',
          display: 'flex',
          flexDirection: 'column',
          paddingBottom: 0,
        }}
      >
        <div className="kb-head">
          <div className="kb-head-left">
            <button className="ghost sm" onClick={onClose} title="关闭">←</button>
            <span className="kb-title">数据中台</span>
            <span className="dim small">{canvas ? `当前画布：${canvas.name}` : '未打开画布'}</span>
          </div>
          <div className="kb-head-right">
            <div className="tabs">
              <div
                className={`tab${tab === 'sources' ? ' active' : ''}`}
                onClick={() => setTab('sources')}
                title="连接：业务库 / 文档库 / HTTP 接口（密钥只存密文）"
              >
                数据源
              </div>
              <div
                className={`tab${tab === 'vector' ? ' active' : ''}`}
                onClick={() => setTab('vector')}
                title="向量库：存向量和原文，按相似度检索（建库与检索必须是同一个）"
              >
                向量库
              </div>
              <div
                className={`tab${tab === 'datasets' ? ' active' : ''}`}
                onClick={() => setTab('datasets')}
                title="数据集：把数据源里的表或查询登记成节点可直接引用的名字"
              >
                数据集{datasets.length ? `（${datasets.length}）` : ''}
              </div>
              <div
                className={`tab${tab === 'service' ? ' active' : ''}`}
                onClick={() => setTab('service')}
                title="外部数据平台接入（HTTP 数据集 API），保存后编译进 integrations.json"
              >
                外部接入
              </div>
            </div>
          </div>
        </div>

        <div className="kb-body" style={{ flex: 1, overflow: 'auto' }}>
          {!canvas ? (
            <div className="kb-empty">先打开一张画布，再配置它的数据源。</div>
          ) : tab === 'sources' ? (
            <ProvidersPanel kind="data" canvasId={canvas.id} />
          ) : tab === 'vector' ? (
            <ProvidersPanel kind="vector" canvasId={canvas.id} />
          ) : tab === 'service' ? (
            <>
              <div className="hint-box" style={{ marginBottom: 12 }}>
                这里配「外部数据平台」接入（HTTP 数据集 API）。保存后编译进生成物的
                <code className="mono"> integrations.json </code>与
                <code className="mono"> integrations/data_client.py</code>，
                Token 只写环境变量名，不落盘。表 / SQL 取数请用「数据集」页。
              </div>
              <label className="row" style={{ gap: 8 }}>
                <input
                  type="checkbox"
                  checked={svc.data.enabled}
                  onChange={(e) => patchSvc('enabled', e.target.checked)}
                  style={{ width: 15, height: 15 }}
                />
                <span className="small">启用外部数据平台（默认只读，写入需单独标 :write）</span>
              </label>
              <label className="field">
                <span>接入方式</span>
                <select value={svc.data.kind} onChange={(e) => patchSvc('kind', e.target.value)}>
                  <option value="http">HTTP 数据集 API</option>
                  <option value="sdk">自定义 SDK（模块名）</option>
                  <option value="jdbc">JDBC（需额外依赖）</option>
                  <option value="s3">S3 兼容（需额外依赖）</option>
                </select>
              </label>
              <label className="field">
                <span>Base URL</span>
                <input
                  value={svc.data.base_url}
                  placeholder="https://data.company.com"
                  onChange={(e) => patchSvc('base_url', e.target.value)}
                />
              </label>
              <div className="row" style={{ gap: 10 }}>
                <label className="field" style={{ flex: 1 }}>
                  <span>认证</span>
                  <select value={svc.data.auth} onChange={(e) => patchSvc('auth', e.target.value)}>
                    <option value="none">无</option>
                    <option value="bearer">Bearer Token</option>
                    <option value="aksk">AK/SK</option>
                    <option value="oidc">OIDC</option>
                  </select>
                </label>
                <label className="field" style={{ flex: 1 }}>
                  <span>Token 环境变量名</span>
                  <input value={svc.data.secret_ref} onChange={(e) => patchSvc('secret_ref', e.target.value)} />
                </label>
              </div>
              <label className="field">
                <span>数据集映射（每行：逻辑名 = 物理表 / 路径，写权限加 :write）</span>
                <textarea
                  rows={4}
                  className="mono"
                  value={datasetsText(svc.data.datasets)}
                  placeholder="customer_orders = dwd.customer_orders"
                  onChange={(e) => patchSvc('datasets', parseDatasets(e.target.value))}
                />
              </label>
              <div className="row" style={{ gap: 10 }}>
                <label className="field" style={{ flex: 1 }}>
                  <span>超时（秒）</span>
                  <input
                    type="number"
                    min={5}
                    value={svc.data.timeout_s}
                    onChange={(e) => patchSvc('timeout_s', Number(e.target.value))}
                  />
                </label>
                <label className="field" style={{ flex: 1 }}>
                  <span>脱敏字段（逗号分隔）</span>
                  <input
                    value={(svc.data.pii_fields || []).join(', ')}
                    placeholder="phone, id_card"
                    onChange={(e) =>
                      patchSvc('pii_fields', e.target.value.split(',').map((s) => s.trim()).filter(Boolean))
                    }
                  />
                </label>
              </div>
              <div className="row" style={{ marginTop: 12 }}>
                <button className="primary" onClick={() => void saveService()} disabled={savingSvc}>
                  {savingSvc ? <span className="spin" /> : null} 保存接入配置
                </button>
              </div>
            </>
          ) : (
            <>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'flex-end', marginBottom: 12 }}>
                <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  <span className="dim small">数据集名（节点里用它取数）</span>
                  <input
                    value={form.logical}
                    placeholder="orders"
                    style={{ width: 160 }}
                    onChange={(e) => setForm({ ...form, logical: e.target.value })}
                  />
                </label>
                <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  <span className="dim small">数据源</span>
                  <select
                    value={form.source_id}
                    style={{ width: 200 }}
                    onChange={(e) => {
                      setForm({ ...form, source_id: e.target.value, table: '' })
                      void loadTables(e.target.value)
                    }}
                  >
                    <option value="">选择数据源…</option>
                    {sources.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.name || s.provider}
                      </option>
                    ))}
                  </select>
                </label>
                <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  <span className="dim small">类型</span>
                  <select
                    value={form.kind}
                    style={{ width: 110 }}
                    onChange={(e) => setForm({ ...form, kind: e.target.value })}
                  >
                    <option value="table">表</option>
                    <option value="sql">SQL</option>
                  </select>
                </label>
                {form.kind === 'table' ? (
                  <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                    <span className="dim small">表</span>
                    <select
                      value={form.table}
                      style={{ width: 200 }}
                      onChange={(e) => setForm({ ...form, table: e.target.value })}
                    >
                      <option value="">{tables.length ? '选择表…' : '先选数据源'}</option>
                      {tables.map((t) => (
                        <option key={t} value={t}>{t}</option>
                      ))}
                    </select>
                  </label>
                ) : (
                  <label style={{ display: 'flex', flexDirection: 'column', gap: 4, flex: 1, minWidth: 280 }}>
                    <span className="dim small">SQL（只允许单条查询）</span>
                    <input
                      value={form.sql}
                      placeholder="select * from orders where status = 'paid'"
                      onChange={(e) => setForm({ ...form, sql: e.target.value })}
                    />
                  </label>
                )}
                <button className="primary" onClick={() => void create()} disabled={busy === 'create'}>
                  {busy === 'create' ? <span className="spin" /> : '+ '}新建数据集
                </button>
                <button onClick={() => void load()} disabled={!!busy}>刷新</button>
              </div>

              {datasets.length === 0 ? (
                <div className="kb-empty">
                  还没有数据集。先在上面建一个：选数据源 → 选表或写 SQL → 起个逻辑名。
                </div>
              ) : (
                <table className="eval-table">
                  <thead>
                    <tr>
                      <th>数据集名</th>
                      <th>类型</th>
                      <th>数据源</th>
                      <th>说明</th>
                      <th style={{ width: 160 }}>操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {datasets.map((ds) => (
                      <tr key={ds.id}>
                        <td><code className="mono">{ds.logical}</code></td>
                        <td>{ds.kind === 'sql' ? 'SQL' : '表'}</td>
                        <td className="dim small">{sourceName(ds.source_id)}</td>
                        <td className="dim small">{ds.description || '—'}</td>
                        <td>
                          <button className="sm" onClick={() => void openPreview(ds)} disabled={!!busy}>
                            {busy === ds.id ? <span className="spin" /> : '预览'}
                          </button>{' '}
                          <button className="sm ghost" onClick={() => void remove(ds)} disabled={!!busy}>
                            删除
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}

              {preview && (
                <div style={{ marginTop: 16 }}>
                  <div className="dim small" style={{ marginBottom: 6 }}>
                    预览 <code className="mono">{preview.name}</code>：{preview.data.statement}
                    （{preview.data.row_count} 行）
                  </div>
                  <div style={{ overflow: 'auto', maxHeight: 260 }}>
                    <table className="eval-table">
                      <thead>
                        <tr>
                          {preview.data.columns.map((c) => (
                            <th key={c}>{c}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {preview.data.rows.map((row, i) => (
                          <tr key={i}>
                            {preview.data.columns.map((c) => (
                              <td key={c}>{String(row[c] ?? '')}</td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}
