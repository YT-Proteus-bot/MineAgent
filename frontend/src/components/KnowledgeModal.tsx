import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { useStore } from '../store'
import type { CatalogItem } from '../types'

/**
 * 知识库：全局的文档集合。
 *
 * 列表 → 创建向导三步（选文件 / 分段与向量配置 / 处理），
 * 参考 Dify 的流程，但只保留当前后端真正支持的字段。
 */

type Step = 1 | 2 | 3

/** 建库模板：只放后端真正能实现的，不做只有壳的选项 */
interface Template {
  id: string
  name: string
  desc: string
  tag: string
  chunk: ChunkCfg
}

const TEMPLATES: Template[] = [
  {
    id: 'blank',
    name: '空白知识流水线',
    desc: '从零开始，分段参数全部自己定，适合结构特殊的文档。',
    tag: '自定义',
    chunk: { separator: '\n', size: 900, overlap: 120 },
  },
  {
    id: 'general',
    name: 'General Mode',
    desc: '按换行切分，再把小段拼到接近上限。最通用，先用这个。',
    tag: '通用',
    chunk: { separator: '\n', size: 900, overlap: 120 },
  },
  {
    id: 'qa',
    name: 'Simple Q&A',
    desc: '按空行切分，每个问答对独立成块。适合 FAQ / 问答格式的文档。',
    tag: '问答',
    chunk: { separator: '\n\n', size: 600, overlap: 60 },
  },
]

interface ChunkCfg {
  separator: string
  size: number
  overlap: number
}

interface ProviderPick {
  provider: string
  config: Record<string, any>
  secret: Record<string, any>
}

const EMPTY_PICK: ProviderPick = { provider: '', config: {}, secret: {} }

function statusText(status: string): string {
  return (
    { draft: '待建索引', building: '索引中', ready: '就绪', failed: '失败' } as Record<
      string,
      string
    >
  )[status] || status
}

function humanSize(n: number): string {
  if (!n) return '0 B'
  if (n > 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`
  if (n > 1024) return `${Math.round(n / 1024)} KB`
  return `${n} B`
}

export default function KnowledgeModal({ onClose }: { onClose: () => void }) {
  const toast = useStore((s) => s.toast)

  const [view, setView] = useState<'list' | 'templates' | 'wizard' | 'external'>('list')
  const [template, setTemplate] = useState<string>('general')
  const [createMenuOpen, setCreateMenuOpen] = useState(false)
  // 外部知识库表单
  const [extName, setExtName] = useState('')
  const [extEndpoint, setExtEndpoint] = useState('')
  const [extKey, setExtKey] = useState('')
  const [extCollection, setExtCollection] = useState('')
  const [extSaving, setExtSaving] = useState(false)
  const [items, setItems] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [keyword, setKeyword] = useState('')

  // 向导状态
  const [step, setStep] = useState<Step>(1)
  const [files, setFiles] = useState<File[]>([])
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [chunk, setChunk] = useState<ChunkCfg>({ separator: '\n', size: 900, overlap: 120 })
  const [embedding, setEmbedding] = useState<ProviderPick>(EMPTY_PICK)
  const [vector, setVector] = useState<ProviderPick>(EMPTY_PICK)
  const [embCatalog, setEmbCatalog] = useState<CatalogItem[]>([])
  const [vecCatalog, setVecCatalog] = useState<CatalogItem[]>([])
  const [groups, setGroups] = useState<Record<string, string>>({})
  const [creating, setCreating] = useState(false)
  const [result, setResult] = useState<{ files: number; chunks: number; dim: number } | null>(
    null,
  )
  const [dragging, setDragging] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  const refresh = async () => {
    setLoading(true)
    try {
      const res = await api.listKnowledge()
      setItems(res.items || [])
    } catch (e: any) {
      toast(`读取知识库失败：${e.message || e}`, 'err')
      setItems([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    refresh()
    api
      .providerCatalog()
      .then((cat) => {
        const emb = cat.kinds.find((k) => k.id === 'embedding')
        const vec = cat.kinds.find((k) => k.id === 'vector')
        setEmbCatalog((emb?.items || []).filter((i) => i.status === 'ready'))
        setVecCatalog((vec?.items || []).filter((i) => i.status === 'ready'))
        setGroups(cat.groups || {})
      })
      .catch(() => {
        /* 拿不到目录就让用户手填 */
      })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const resetWizard = () => {
    setStep(1)
    setFiles([])
    setName('')
    setDescription('')
    setChunk({ separator: '\n', size: 900, overlap: 120 })
    setEmbedding(EMPTY_PICK)
    setVector(EMPTY_PICK)
    setResult(null)
    setCreating(false)
  }

  const startCreate = (tpl = 'general') => {
    const found = TEMPLATES.find((t) => t.id === tpl) || TEMPLATES[1]
    resetWizard()
    setTemplate(found.id)
    setChunk({ ...found.chunk })
    setView('wizard')
    setCreateMenuOpen(false)
  }

  const startExternal = () => {
    setExtName('')
    setExtEndpoint('')
    setExtKey('')
    setExtCollection('')
    setView('external')
    setCreateMenuOpen(false)
  }

  const submitExternal = async () => {
    if (!extName.trim()) {
      toast('给知识库起个名字', 'err')
      return
    }
    setExtSaving(true)
    try {
      await api.createKnowledge({
        kind: 'external',
        name: extName.trim(),
        endpoint: extEndpoint.trim(),
        api_key: extKey,
        collection: extCollection.trim(),
      })
      toast('外部知识库已接入', 'ok')
      setView('list')
      refresh()
    } catch (e: any) {
      toast(`接入失败：${e.message || e}`, 'err')
    } finally {
      setExtSaving(false)
    }
  }

  const addFiles = (list: FileList | File[] | null | undefined) => {
    if (!list) return
    const incoming = Array.from(list)
    setFiles((prev) => {
      const names = new Set(prev.map((f) => f.name))
      return [...prev, ...incoming.filter((f) => !names.has(f.name))]
    })
  }

  const pickFields = (item: CatalogItem | undefined) =>
    (item?.fields || []).filter((f) => f.required || f.secret)

  const setPickValue = (
    pick: ProviderPick,
    setPick: (v: ProviderPick) => void,
    field: { key: string; secret: boolean },
    value: string,
  ) => {
    if (field.secret) {
      setPick({ ...pick, secret: { ...pick.secret, [field.key]: value } })
    } else {
      setPick({ ...pick, config: { ...pick.config, [field.key]: value } })
    }
  }

  const providerForm = (
    kindLabel: string,
    catalog: CatalogItem[],
    pick: ProviderPick,
    setPick: (v: ProviderPick) => void,
  ) => {
    const current = catalog.find((i) => i.id === pick.provider)
    const fields = pickFields(current)
    return (
      <div className="kb-form-block">
        <div className="kb-form-label">{kindLabel}</div>
        <select
          value={pick.provider}
          onChange={(e) => setPick({ provider: e.target.value, config: {}, secret: {} })}
        >
          <option value="">选择厂商…</option>
          {Object.entries(
            catalog.reduce<Record<string, CatalogItem[]>>((acc, item) => {
              const key = item.group || 'other'
              ;(acc[key] = acc[key] || []).push(item)
              return acc
            }, {}),
          ).map(([group, list]) => (
            <optgroup key={group} label={groups[group] || group}>
              {list.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label}
                </option>
              ))}
            </optgroup>
          ))}
        </select>
        {current && fields.length > 0 && (
          <div className="kb-field-grid">
            {fields.map((field) => {
              const modelOptions =
                field.key === 'model' ? current.models || [] : []
              const value =
                (field.secret ? pick.secret[field.key] : pick.config[field.key]) ?? ''
              return (
                <label key={field.key} className="kb-field">
                  <span>
                    {field.label}
                    {field.required ? ' *' : ''}
                  </span>
                  {modelOptions.length > 0 ? (
                    <select
                      value={String(value)}
                      onChange={(e) =>
                        setPickValue(pick, setPick, field, e.target.value)
                      }
                    >
                      <option value="">选择模型…</option>
                      {modelOptions.map((m) => (
                        <option key={m.id} value={m.id}>
                          {m.id}
                          {m.dim ? `（${m.dim} 维）` : ''}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <input
                      type={field.secret ? 'password' : 'text'}
                      placeholder={field.placeholder || field.default || ''}
                      value={String(value)}
                      onChange={(e) =>
                        setPickValue(pick, setPick, field, e.target.value)
                      }
                    />
                  )}
                </label>
              )
            })}
          </div>
        )}
        {current && fields.length === 0 && (
          <div className="dim small" style={{ marginTop: 4 }}>
            这个厂商不需要额外配置
          </div>
        )}
      </div>
    )
  }

  const canNext = () => {
    if (step === 1) return files.length > 0
    if (step === 2) return !!embedding.provider && !!vector.provider
    return false
  }

  const submit = async () => {
    if (!files.length) {
      toast('先选一些文件', 'err')
      return
    }
    setCreating(true)
    setStep(3)
    setResult(null)
    try {
      // 1) 建库
      const created = await api.createKnowledge({
        name: name.trim() || files[0].name.replace(/\.[^.]+$/, ''),
        description,
        template,
        chunk,
        embedding: { provider: embedding.provider, config: embedding.config, secret: embedding.secret },
        vector: { provider: vector.provider, config: vector.config, secret: vector.secret },
      })
      const kbId = created.kb?.id
      if (!kbId) throw new Error('创建失败：没有拿到知识库 id')

      // 2) 上传文件
      for (const file of files) {
        await api.uploadKbFile(kbId, file)
      }

      // 3) 建索引
      const built = await api.buildKnowledge(kbId)
      setResult({ files: built.files, chunks: built.chunks, dim: built.dim })
      toast(`知识库已就绪：${built.chunks} 个片段`, 'ok')
      refresh()
    } catch (e: any) {
      toast(`建库失败：${e.message || e}`, 'err')
    } finally {
      setCreating(false)
    }
  }

  const removeKb = async (id: string, kbName: string) => {
    if (!window.confirm(`删除知识库「${kbName}」？索引和文件都会清掉。`)) return
    try {
      await api.deleteKnowledge(id)
      toast('已删除', 'ok')
      refresh()
    } catch (e: any) {
      toast(`删除失败：${e.message || e}`, 'err')
    }
  }

  const filtered = items.filter(
    (it) => !keyword.trim() || String(it.name || '').includes(keyword.trim()),
  )

  return (
    <div className="kb-overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="kb-panel">
        <div className="kb-head">
          <div className="kb-head-left">
            <button className="ghost sm" onClick={onClose} title="关闭">
              ←
            </button>
            <span className="kb-title">知识库</span>
            {view === 'wizard' && (
              <span className="dim small">{step === 1 ? '选择数据源' : step === 2 ? '文本分段与清洗' : '处理并完成'}</span>
            )}
            {view === 'templates' && <span className="dim small">构建自定义知识库</span>}
            {view === 'external' && <span className="dim small">连接外部知识库</span>}
          </div>
          {view === 'list' ? (
            <div className="kb-head-right">
              <input
                className="kb-search"
                placeholder="搜索知识库"
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
              />
              <div className="kb-create-wrap">
                <button
                  className="primary sm"
                  onClick={() => setCreateMenuOpen((v) => !v)}
                >
                  ＋ 创建 ▾
                </button>
                {createMenuOpen && (
                  <div className="kb-menu">
                    <button onClick={() => startCreate('general')}>
                      <span>＋</span> 创建即用型知识库
                      <em>上传文档直接建，最快</em>
                    </button>
                    <button
                      onClick={() => {
                        setView('templates')
                        setCreateMenuOpen(false)
                      }}
                    >
                      <span>⚙</span> 构建自定义知识库
                      <em>先选模板，再定分段策略</em>
                    </button>
                    <div className="kb-menu-sep" />
                    <button onClick={startExternal}>
                      <span>◎</span> 连接外部知识库
                      <em>已有库，填地址和密钥接入</em>
                    </button>
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div className="kb-steps">
              {[1, 2, 3].map((n) => (
                <div key={n} className={`kb-step${step === n ? ' active' : ''}${step > n ? ' done' : ''}`}>
                  <span className="kb-step-dot">{step > n ? '✓' : n}</span>
                  {n === 1 ? '选择数据源' : n === 2 ? '文本分段与清洗' : '处理并完成'}
                </div>
              ))}
            </div>
          )}
        </div>

        {view === 'list' ? (
          <div className="kb-body">
            {loading ? (
              <div className="kb-empty">读取中…</div>
            ) : filtered.length === 0 ? (
              <div className="kb-empty">
                <div className="kb-empty-icon">▤</div>
                <div style={{ marginBottom: 4 }}>
                  {items.length ? '没有匹配的知识库' : '创建你的第一个知识库'}
                </div>
                <div className="dim small" style={{ marginBottom: 16 }}>
                  上传文档 → 选向量模型和向量库 → 建索引，之后画布里的检索节点就能用
                </div>
                <div className="kb-start-list">
                  <button className="kb-start-card" onClick={() => startCreate('general')}>
                    <span className="kb-start-icon">＋</span>
                    <span>
                      <b>创建即用型知识库</b>
                      <span className="dim small">上传文档，切分后向量化入库</span>
                    </span>
                    <span className="kb-badge">推荐</span>
                  </button>
                  <button
                    className="kb-start-card"
                    onClick={() => setView('templates')}
                  >
                    <span className="kb-start-icon">⚙</span>
                    <span>
                      <b>构建自定义知识库</b>
                      <span className="dim small">先选模板，再定分段策略</span>
                    </span>
                  </button>
                  <button className="kb-start-card" onClick={startExternal}>
                    <span className="kb-start-icon">◎</span>
                    <span>
                      <b>连接外部知识库</b>
                      <span className="dim small">已有库，填地址和密钥直接接入</span>
                    </span>
                  </button>
                </div>
              </div>
            ) : (
              <div className="kb-grid">
                {filtered.map((it) => (
                  <div key={it.id} className="kb-card">
                    <div className="kb-card-top">
                      <span className="kb-card-icon">▤</span>
                      <span className={`kb-status kb-status-${it.status}`}>
                        {statusText(it.status)}
                      </span>
                    </div>
                    <div className="kb-card-name" title={it.name}>
                      {it.name}
                    </div>
                    <div className="dim small">
                      {it.kind === 'external'
                        ? '外部接入 · 不占本地存储'
                        : `${it.file_count || 0} 个文件 · ${it.chunk_count || 0} 个片段`}
                    </div>
                    <div className="dim small">
                      {it.kind === 'external'
                        ? String(it.endpoint || '').replace(/^https?:\/\//, '').slice(0, 34)
                        : `${it.embedding_provider || '—'} / ${it.vector_provider || '—'}`}
                    </div>
                    {it.error && (
                      <div className="kb-card-error" title={it.error}>
                        {String(it.error).slice(0, 60)}
                      </div>
                    )}
                    <div className="kb-card-actions">
                      <button className="sm" onClick={() => removeKb(it.id, it.name)}>
                        删除
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        ) : view === 'templates' ? (
          <div className="kb-body">
            <div className="kb-tpl-hint">
              选一个起步模板，下一步还能改分段参数。
            </div>
            <div className="kb-grid">
              {TEMPLATES.map((t) => (
                <button
                  key={t.id}
                  className={`kb-card kb-tpl${template === t.id ? ' active' : ''}`}
                  onClick={() => startCreate(t.id)}
                >
                  <div className="kb-card-top">
                    <span className="kb-card-icon">▤</span>
                    <span className="kb-status">{t.tag}</span>
                  </div>
                  <div className="kb-card-name">{t.name}</div>
                  <div className="dim small">{t.desc}</div>
                  <div className="kb-tpl-foot">
                    <span className="kb-link">选择 →</span>
                  </div>
                </button>
              ))}
            </div>
            <div className="kb-foot">
              <button className="sm" onClick={() => setView('list')}>
                ← 返回列表
              </button>
              <span />
            </div>
          </div>
        ) : view === 'external' ? (
          <div className="kb-body">
            <div className="kb-step-body">
              <div className="kb-form-block">
                <div className="kb-form-label">名称</div>
                <input
                  value={extName}
                  onChange={(e) => setExtName(e.target.value)}
                  placeholder="例如：Dify 产品文档库"
                />
              </div>
              <div className="kb-form-block">
                <div className="kb-form-label">检索地址 *</div>
                <input
                  value={extEndpoint}
                  onChange={(e) => setExtEndpoint(e.target.value)}
                  placeholder="https://api.dify.ai/v1/datasets/xxx/retrieve"
                />
                <div className="dim small">
                  会向这个地址 POST <code>{'{ query, top_k }'}</code>，
                  返回里能识别 records / results / data 等常见结构
                </div>
              </div>
              <div className="kb-field-grid">
                <label className="kb-field">
                  <span>API Key（可选）</span>
                  <input
                    type="password"
                    value={extKey}
                    onChange={(e) => setExtKey(e.target.value)}
                    placeholder="放在 Authorization: Bearer 里"
                  />
                </label>
                <label className="kb-field">
                  <span>库标识（可选）</span>
                  <input
                    value={extCollection}
                    onChange={(e) => setExtCollection(e.target.value)}
                    placeholder="外部系统的 dataset / collection id"
                  />
                </label>
              </div>
            </div>
            <div className="kb-foot">
              <button className="sm" onClick={() => setView('list')}>
                ← 返回列表
              </button>
              <button
                className="primary sm"
                disabled={extSaving}
                onClick={submitExternal}
              >
                {extSaving ? '接入中…' : '接入'}
              </button>
            </div>
          </div>
        ) : (
          <div className="kb-body">
            {step === 1 && (
              <div className="kb-step-body">
                <div className="kb-form-block">
                  <div className="kb-form-label">上传文本文件</div>
                  <div
                    className={`kb-drop${dragging ? ' dragging' : ''}`}
                    onDragOver={(e) => {
                      e.preventDefault()
                      setDragging(true)
                    }}
                    onDragLeave={() => setDragging(false)}
                    onDrop={(e) => {
                      e.preventDefault()
                      setDragging(false)
                      addFiles(e.dataTransfer?.files)
                    }}
                    onClick={() => fileRef.current?.click()}
                  >
                    <div style={{ fontSize: 20, marginBottom: 6 }}>⇪</div>
                    <div>
                      拖拽文件至此，或者 <span className="kb-link">选择文件</span>
                    </div>
                    <div className="dim small" style={{ marginTop: 6 }}>
                      支持 TXT / MD / HTML / CSV / JSON / PDF / DOCX，单个不超过 30MB
                    </div>
                  </div>
                  <input
                    ref={fileRef}
                    type="file"
                    multiple
                    style={{ display: 'none' }}
                    onChange={(e) => {
                      addFiles(e.target.files)
                      e.currentTarget.value = ''
                    }}
                  />
                </div>

                {files.length > 0 && (
                  <div className="kb-form-block">
                    <div className="kb-form-label">已选 {files.length} 个文件</div>
                    <div className="kb-file-list">
                      {files.map((f) => (
                        <div key={f.name} className="kb-file-row">
                          <span className="kb-file-name" title={f.name}>
                            {f.name}
                          </span>
                          <span className="dim small">{humanSize(f.size)}</span>
                          <button
                            className="sm"
                            onClick={() => setFiles((prev) => prev.filter((x) => x.name !== f.name))}
                          >
                            ×
                          </button>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}

            {step === 2 && (
              <div className="kb-step-body">
                <div className="kb-form-block">
                  <div className="kb-form-label">分段设置</div>
                  <div className="kb-field-grid three">
                    <label className="kb-field">
                      <span>分段标识符</span>
                      <input
                        value={chunk.separator}
                        onChange={(e) => setChunk({ ...chunk, separator: e.target.value })}
                        placeholder="\n"
                      />
                    </label>
                    <label className="kb-field">
                      <span>最大长度（字符）</span>
                      <input
                        type="number"
                        value={chunk.size}
                        onChange={(e) => setChunk({ ...chunk, size: Number(e.target.value) || 900 })}
                      />
                    </label>
                    <label className="kb-field">
                      <span>重叠长度（字符）</span>
                      <input
                        type="number"
                        value={chunk.overlap}
                        onChange={(e) =>
                          setChunk({ ...chunk, overlap: Number(e.target.value) || 0 })
                        }
                      />
                    </label>
                  </div>
                  <div className="dim small" style={{ marginTop: 6 }}>
                    按分隔符保留语义边界，再把小段拼到接近最大长度，相邻块之间留重叠。
                  </div>
                </div>

                {providerForm('Embedding 模型', embCatalog, embedding, setEmbedding)}
                {providerForm('向量库', vecCatalog, vector, setVector)}

                <div className="kb-form-block">
                  <div className="kb-form-label">知识库名称</div>
                  <input
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder={files[0]?.name.replace(/\.[^.]+$/, '') || '给知识库起个名字'}
                  />
                  <input
                    style={{ marginTop: 6 }}
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    placeholder="描述（可选）"
                  />
                </div>
              </div>
            )}

            {step === 3 && (
              <div className="kb-step-body">
                <div className="kb-result">
                  {creating ? (
                    <>
                      <div className="kb-result-icon spin">◌</div>
                      <div style={{ fontSize: 15, fontWeight: 600 }}>正在处理…</div>
                      <div className="dim small" style={{ marginTop: 6 }}>
                        上传文件 → 切分 → 向量化 → 写入向量库，文件多时需要一会儿
                      </div>
                    </>
                  ) : result ? (
                    <>
                      <div className="kb-result-icon ok">✓</div>
                      <div style={{ fontSize: 15, fontWeight: 600 }}>知识库已创建</div>
                      <div className="dim small" style={{ marginTop: 8 }}>
                        {result.files} 个文件 · {result.chunks} 个片段 · 向量维度 {result.dim}
                      </div>
                      <div className="kb-result-actions">
                        <button className="primary sm" onClick={onClose}>
                          完成
                        </button>
                        <button className="sm" onClick={() => startCreate()}>
                          再建一个
                        </button>
                      </div>
                    </>
                  ) : (
                    <>
                      <div className="kb-result-icon err">!</div>
                      <div style={{ fontSize: 15, fontWeight: 600 }}>处理失败</div>
                      <div className="dim small" style={{ marginTop: 6 }}>
                        看右下角的提示，修正后可以回到上一步重试
                      </div>
                      <div className="kb-result-actions">
                        <button className="sm" onClick={() => setStep(2)}>
                          回到上一步
                        </button>
                      </div>
                    </>
                  )}
                </div>
              </div>
            )}

            <div className="kb-foot">
              <div>
                {step === 2 && (
                  <button className="sm" onClick={() => setStep(1)} disabled={creating}>
                    ← 上一步
                  </button>
                )}
                {step === 1 && (
                  <button className="sm" onClick={() => setView('list')}>
                    ← 返回列表
                  </button>
                )}
              </div>
              <div>
                {step === 1 && (
                  <button className="primary sm" disabled={!canNext()} onClick={() => setStep(2)}>
                    下一步 →
                  </button>
                )}
                {step === 2 && (
                  <button
                    className="primary sm"
                    disabled={!canNext() || creating}
                    onClick={submit}
                  >
                    保存并处理
                  </button>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
