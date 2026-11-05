import { useMemo, useState } from 'react'
import { useStore } from '../store'
import type { CustomRule, CustomRuleTypeId } from '../types'

const LEVEL_STYLE: Record<string, { label: string; cls: string }> = {
  error: { label: '错误', cls: 'err' },
  warn: { label: '警告', cls: 'warn' },
  info: { label: '提示', cls: 'info' },
}

const TYPE_LABEL: Record<string, string> = {
  order: '顺序约束',
  require_kind: '必须包含',
  forbid_kind: '禁止出现',
  max_count: '数量上限',
}

function ruleSummary(r: CustomRule, nameOf: (id?: string) => string): string {
  switch (r.type) {
    case 'order':
      return r.mode === 'before'
        ? `「${nameOf(r.node)}」必须在「${nameOf(r.anchor)}」之前`
        : `「${nameOf(r.node)}」必须在「${nameOf(r.anchor)}」之后`
    case 'require_kind':
      return `必须包含 ${r.kind} 类型的节点`
    case 'forbid_kind':
      return `不允许出现 ${r.kind} 类型的节点`
    case 'max_count':
      return `${r.kind} 类型最多 ${r.count} 个`
    default:
      return r.type
  }
}

export default function ConstraintPanel({ onClose }: { onClose: () => void }) {
  const report = useStore((s) => s.constraintReport)
  const validateNow = useStore((s) => s.validateNow)
  const rules = useStore((s) => s.canvas?.rules || [])
  const addRule = useStore((s) => s.addRule)
  const removeRule = useStore((s) => s.removeRule)
  const nodes = useStore((s) => s.nodes)
  const meta = useStore((s) => s.meta)
  const setSelected = useStore((s) => s.setSelected)
  const setInspectorTab = useStore((s) => s.setInspectorTab)

  const [adding, setAdding] = useState(false)
  const [draft, setDraft] = useState<CustomRule>({
    id: '',
    type: 'order',
    level: 'error',
    mode: 'after',
  })

  const nodeName = useMemo(() => {
    const map = new Map(nodes.map((n) => [n.id, n.data.label || n.data.name]))
    return (id?: string) => (id ? map.get(id) || id : '—')
  }, [nodes])

  const kindOptions = useMemo(
    () => (meta?.nodes || []).map((n) => ({ value: n.kind, label: `${n.label}（${n.kind}）` })),
    [meta],
  )

  const errors = report?.errors || []
  const warns = report?.warnings || []
  const infos = report?.infos || []

  const jumpTo = (nodeIds: string[]) => {
    const first = nodeIds.find((id) => nodes.some((n) => n.id === id))
    if (first) {
      setSelected(first)
      setInspectorTab('props')
    }
  }

  const submitRule = async () => {
    if (draft.type === 'order' && (!draft.node || !draft.anchor)) return
    if (draft.type !== 'order' && !draft.kind) return
    const rule: CustomRule = {
      ...draft,
      id: `r_${Date.now().toString(36)}`,
      label: ruleSummary(draft, nodeName),
    }
    await addRule(rule)
    setAdding(false)
    setDraft({ id: '', type: 'order', level: 'error', mode: 'after' })
  }

  const renderViolation = (v: any, idx: number) => {
    const st = LEVEL_STYLE[v.level] || LEVEL_STYLE.info
    return (
      <div key={`${v.rule}-${idx}`} className={`cv-item level-${st.cls}`}>
        <div className="cv-item-head">
          <span className={`cv-dot ${st.cls}`} />
          <span className="cv-title">{v.title}</span>
          {v.category && <span className="badge" style={{ marginLeft: 'auto' }}>{v.category}</span>}
        </div>
        <div className="cv-msg">{v.message}</div>
        {v.hint && <div className="cv-hint">{v.hint}</div>}
        {v.nodes?.length > 0 && (
          <button className="sm" style={{ marginTop: 6 }} onClick={() => jumpTo(v.nodes)}>
            定位到节点（{v.nodes.length}）
          </button>
        )}
      </div>
    )
  }

  return (
    <div className="constraint-panel">
      <div className="bg-panel-head">
        <span>编排约束</span>
        <button className="ghost sm" onClick={() => validateNow()} title="重新检查">
          ↻ 检查
        </button>
        <button className="ghost icon" onClick={onClose} title="关闭">
          ✕
        </button>
      </div>

      <div className="bg-panel-body">
        <div className="cv-stats">
          <span className={`badge ${errors.length ? 'err' : 'ok'}`}>{errors.length} 错误</span>
          <span className={`badge ${warns.length ? 'warn' : ''}`}>{warns.length} 警告</span>
          <span className="badge">{infos.length} 提示</span>
          <div style={{ flex: 1 }} />
          <span className="dim small">检查 {report?.checked_rules ?? 0} 条规则</span>
        </div>

        {!report && <div className="dim small">正在检查…</div>}

        {report && errors.length === 0 && warns.length === 0 && infos.length === 0 && (
          <div className="hint-box" style={{ borderColor: '#1d4b3b', color: 'var(--ok)' }}>
            全部通过，没有发现编排问题。
          </div>
        )}

        {errors.length > 0 && (
          <>
            <div className="bg-section-title" style={{ marginTop: 12 }}>必须修复（会阻止运行）</div>
            {errors.map(renderViolation)}
          </>
        )}

        {warns.length > 0 && (
          <>
            <div className="bg-section-title" style={{ marginTop: 12 }}>建议优化</div>
            {warns.map(renderViolation)}
          </>
        )}

        {infos.length > 0 && (
          <>
            <div className="bg-section-title" style={{ marginTop: 12 }}>提示</div>
            {infos.map(renderViolation)}
          </>
        )}

        <div className="bg-section-title" style={{ marginTop: 16 }}>
          画布自定义规则（{rules.length}）
        </div>
        {rules.length === 0 && (
          <div className="dim small" style={{ marginBottom: 8 }}>
            还没有自定义规则。可以约束「某节点必须在某节点之后」「禁止某类节点」等。
          </div>
        )}
        {rules.map((r) => (
          <div key={r.id} className="cv-rule">
            <span className={`badge ${r.level === 'error' ? 'err' : 'warn'}`}>
              {r.level === 'error' ? '拦截' : '提示'}
            </span>
            <span className="cv-rule-text">{ruleSummary(r, nodeName)}</span>
            <button className="ghost sm" onClick={() => removeRule(r.id)} title="删除">
              ✕
            </button>
          </div>
        ))}

        {!adding ? (
          <button className="sm" style={{ marginTop: 6 }} onClick={() => setAdding(true)}>
            ＋ 添加规则
          </button>
        ) : (
          <div className="cv-form">
            <label className="field">
              <span>规则类型</span>
              <select
                value={draft.type}
                onChange={(e) =>
                  setDraft({ ...draft, type: e.target.value as CustomRuleTypeId })
                }
              >
                {(meta?.custom_rule_types || []).map((t) => (
                  <option key={t.type} value={t.type}>
                    {t.label}
                  </option>
                ))}
              </select>
            </label>

            {draft.type === 'order' ? (
              <>
                <label className="field">
                  <span>节点</span>
                  <select
                    value={draft.node || ''}
                    onChange={(e) => setDraft({ ...draft, node: e.target.value })}
                  >
                    <option value="">请选择…</option>
                    {nodes.map((n) => (
                      <option key={n.id} value={n.id}>
                        {n.data.label}（{n.data.name}）
                      </option>
                    ))}
                  </select>
                </label>
                <label className="field">
                  <span>相对关系</span>
                  <select
                    value={draft.mode || 'after'}
                    onChange={(e) =>
                      setDraft({ ...draft, mode: e.target.value as 'after' | 'before' })
                    }
                  >
                    <option value="after">必须在…之后</option>
                    <option value="before">必须在…之前</option>
                  </select>
                </label>
                <label className="field">
                  <span>参照节点</span>
                  <select
                    value={draft.anchor || ''}
                    onChange={(e) => setDraft({ ...draft, anchor: e.target.value })}
                  >
                    <option value="">请选择…</option>
                    {nodes.map((n) => (
                      <option key={n.id} value={n.id}>
                        {n.data.label}（{n.data.name}）
                      </option>
                    ))}
                  </select>
                </label>
              </>
            ) : (
              <>
                <label className="field">
                  <span>节点类型</span>
                  <select
                    value={draft.kind || ''}
                    onChange={(e) => setDraft({ ...draft, kind: e.target.value })}
                  >
                    <option value="">请选择…</option>
                    {kindOptions.map((k) => (
                      <option key={k.value} value={k.value}>
                        {k.label}
                      </option>
                    ))}
                  </select>
                </label>
                {draft.type === 'max_count' && (
                  <label className="field">
                    <span>最多几个</span>
                    <input
                      type="number"
                      min={0}
                      value={draft.count ?? 1}
                      onChange={(e) => setDraft({ ...draft, count: Number(e.target.value) })}
                    />
                  </label>
                )}
              </>
            )}

            <label className="field">
              <span>强度</span>
              <select
                value={draft.level || 'error'}
                onChange={(e) =>
                  setDraft({ ...draft, level: e.target.value as 'error' | 'warn' })
                }
              >
                <option value="error">拦截（不满足就不能运行）</option>
                <option value="warn">提示（只提醒）</option>
              </select>
            </label>

            {draft.type === 'order' && draft.node && draft.anchor && (
              <div className="hint-box" style={{ marginTop: 0 }}>
                预览：{ruleSummary(draft, nodeName)}
              </div>
            )}

            <div className="row" style={{ marginTop: 8 }}>
              <button className="primary sm" onClick={submitRule}>
                添加
              </button>
              <button className="sm" onClick={() => setAdding(false)}>
                取消
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
