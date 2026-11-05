import { useMemo, useState } from 'react'
import { useStore } from '../store'
import { isAgentKind, type AgentOrg } from '../types'
import CodeEditor from './CodeEditor'
import NodeModelModal from './NodeModelModal'

function ParamField({
  def,
  value,
  onChange,
}: {
  def: {
    key: string
    label: string
    default: any
    placeholder: string
    options?: { value: string; label: string }[]
    help?: string
  }
  value: any
  onChange: (v: any) => void
}) {
  if (def.options && def.options.length) {
    return (
      <label className="field">
        <span>{def.label}</span>
        <select value={value ?? def.default ?? ''} onChange={(e) => onChange(e.target.value)}>
          {def.options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        {def.help && (
          <div className="dim small" style={{ marginTop: 4, lineHeight: 1.5 }}>
            {def.help}
          </div>
        )}
      </label>
    )
  }

  const kind = Array.isArray(def.default)
    ? 'array'
    : typeof def.default === 'boolean'
      ? 'boolean'
      : typeof def.default === 'number'
        ? 'number'
        : def.default !== null && typeof def.default === 'object'
          ? 'json'
          : 'string'

  if (kind === 'json') {
    const current =
      typeof value === 'string' ? value : JSON.stringify(value ?? def.default ?? {}, null, 2)
    return (
      <label className="field">
        <span>{def.label}</span>
        <textarea
          key={current}
          rows={4}
          className="mono"
          defaultValue={current}
          onBlur={(e) => {
            try {
              onChange(JSON.parse(e.target.value))
            } catch {
              onChange(e.target.value)
            }
          }}
        />
      </label>
    )
  }

  if (kind === 'boolean') {
    return (
      <label className="field row" style={{ gap: 8 }}>
        <input
          type="checkbox"
          checked={!!value}
          onChange={(e) => onChange(e.target.checked)}
          style={{ width: 15, height: 15 }}
        />
        <span style={{ margin: 0 }}>{def.label}</span>
      </label>
    )
  }

  if (kind === 'number') {
    return (
      <label className="field">
        <span>{def.label}</span>
        <input
          type="number"
          value={value ?? def.default ?? 0}
          onChange={(e) => onChange(Number(e.target.value))}
        />
      </label>
    )
  }

  if (kind === 'array') {
    const text = Array.isArray(value) ? value.join(', ') : String(value ?? '')
    return (
      <label className="field">
        <span>{def.label}（逗号分隔）</span>
        <input
          value={text}
          placeholder={def.placeholder}
          onChange={(e) =>
            onChange(
              e.target.value
                .split(',')
                .map((s) => s.trim())
                .filter(Boolean),
            )
          }
        />
      </label>
    )
  }

  const long = /system|skill_text|text|description|persona|prompt/.test(def.key) || String(value ?? '').length > 60
  return (
    <label className="field">
      <span>{def.label}</span>
      {long ? (
        <textarea
          rows={3}
          value={value ?? ''}
          placeholder={def.placeholder}
          onChange={(e) => onChange(e.target.value)}
        />
      ) : (
        <input
          value={value ?? ''}
          placeholder={def.placeholder}
          onChange={(e) => onChange(e.target.value)}
        />
      )}
    </label>
  )
}

export default function NodeInspector() {
  const node = useStore((s) => s.nodes.find((n) => n.id === s.selectedNodeId) || null)
  const allNodes = useStore((s) => s.nodes)
  const meta = useStore((s) => s.meta)
  const canvas = useStore((s) => s.canvas)
  const updateNode = useStore((s) => s.updateNode)
  const updateNodeOrg = useStore((s) => s.updateNodeOrg)
  const removeNode = useStore((s) => s.removeNode)
  const duplicateNode = useStore((s) => s.duplicateNode)
  const setSelected = useStore((s) => s.setSelected)
  const tab = useStore((s) => s.inspectorTab)
  const setTab = useStore((s) => s.setInspectorTab)
  const [showModel, setShowModel] = useState(false)

  const def = useMemo(
    () => meta?.nodes.find((n) => n.kind === node?.data.kind),
    [meta, node?.data.kind],
  )

  if (!node) {
    return (
      <aside className="inspector">
        <div className="inspector-head">
          <span className="dim">未选中节点</span>
        </div>
        <div className="inspector-body">
          <div className="hint-box" style={{ lineHeight: 1.9 }}>
            <b>快捷键</b>
            <br />· 右键画布：新增任意节点
            <br />· 右键节点：编辑 / 复制 / 删除
            <br />· 拖动节点右侧圆点连到另一个节点：编排流程
            <br />· 拖动节点本身：调整位置
            <br />· 选中节点或连线后按 Delete：删除
            <br />· Ctrl/Cmd + S：保存并落盘
          </div>
          <div className="hint-box">
            <b>当前画布</b>
            <br />
            名称：{canvas?.name}
            <br />
            项目目录：projects/{canvas?.slug}
            <br />
            框架：{canvas?.framework}
          </div>
        </div>
      </aside>
    )
  }

  const data = node.data
  const isAgent = isAgentKind(data.kind)
  const rawOrg = (data.org || {}) as Partial<AgentOrg>
  const org: AgentOrg = {
    superior: rawOrg.superior || '',
    subordinates: rawOrg.subordinates || [],
    peers: rawOrg.peers || [],
  }
  const agentCandidates = allNodes.filter((n) => n.id !== node.id && isAgentKind(n.data.kind))
  const nodeModel = (data.model || {}) as Record<string, any>

  return (
    <aside className="inspector">
      <div className="inspector-head">
        <div
          className="node-icon"
          style={{ background: def?.color || '#8b5cf6', width: 24, height: 24 }}
        >
          {def?.icon || '◆'}
        </div>
        <div style={{ flex: 1, overflow: 'hidden' }}>
          <input
            value={data.label}
            onChange={(e) => updateNode(node.id, { label: e.target.value })}
            style={{ border: 'none', background: 'transparent', padding: 0, fontSize: 13.5, fontWeight: 600 }}
          />
        </div>
        <button className="ghost icon" onClick={() => setSelected(null)} title="关闭">
          ✕
        </button>
      </div>

      <div className="inspector-tabs">
        <div className={`tab${tab === 'props' ? ' active' : ''}`} onClick={() => setTab('props')}>
          属性
        </div>
        <div className={`tab${tab === 'code' ? ' active' : ''}`} onClick={() => setTab('code')}>
          代码逻辑
        </div>
      </div>

      <div className="inspector-body">
        {tab === 'props' ? (
          <>
            <label className="field">
              <span>节点标识（生成 nodes/{data.name || 'xxx'}.py）</span>
              <input
                value={data.name}
                className="mono"
                onChange={(e) =>
                  updateNode(node.id, { name: e.target.value.replace(/[^\w\u4e00-\u9fff]/g, '_') })
                }
              />
            </label>
            <label className="field">
              <span>说明</span>
              <textarea
                rows={2}
                value={data.description}
                onChange={(e) => updateNode(node.id, { description: e.target.value })}
              />
            </label>

            {isAgent && (
              <>
                <div className="dim small" style={{ margin: '14px 0 8px', letterSpacing: 0.4 }}>
                  模型
                </div>
                <div className="row">
                  <button className="sm" onClick={() => setShowModel(true)}>
                    ⚙ 配置这个 agent 的模型 / Key
                  </button>
                  {nodeModel.has_key ? (
                    <span className="badge ok">独立 Key</span>
                  ) : (
                    <span className="dim small">跟随画布 / 全局</span>
                  )}
                  <div style={{ flex: 1 }} />
                  {nodeModel.model && <span className="dim small mono">{nodeModel.model}</span>}
                </div>

                <div className="dim small" style={{ margin: '16px 0 8px', letterSpacing: 0.4 }}>
                  组织关系
                </div>
                <label className="field">
                  <span>上级 agent</span>
                  <select
                    value={org.superior}
                    onChange={(e) => updateNodeOrg(node.id, { superior: e.target.value })}
                  >
                    <option value="">（无，我是顶层）</option>
                    {agentCandidates.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.data.label}
                      </option>
                    ))}
                  </select>
                </label>

                <div className="field">
                  <span>下级 agent（可以被我分派任务）</span>
                  <div className="org-list">
                    {agentCandidates.length === 0 && (
                      <div className="dim small">画布上还没有其它 agent 节点</div>
                    )}
                    {agentCandidates.map((c) => (
                      <label key={c.id} className="org-item">
                        <input
                          type="checkbox"
                          checked={org.subordinates.includes(c.id)}
                          onChange={(e) =>
                            updateNodeOrg(node.id, {
                              subordinates: e.target.checked
                                ? [...org.subordinates, c.id]
                                : org.subordinates.filter((x) => x !== c.id),
                            })
                          }
                        />
                        <span className="org-name">{c.data.label}</span>
                        <span className="dim mono small">{c.data.name}</span>
                      </label>
                    ))}
                  </div>
                </div>

                <div className="field">
                  <span>平级 agent（同级协作 / 上下文互通）</span>
                  <div className="org-list">
                    {agentCandidates.map((c) => (
                      <label key={c.id} className="org-item">
                        <input
                          type="checkbox"
                          checked={org.peers.includes(c.id)}
                          onChange={(e) =>
                            updateNodeOrg(node.id, {
                              peers: e.target.checked
                                ? [...org.peers, c.id]
                                : org.peers.filter((x) => x !== c.id),
                            })
                          }
                        />
                        <span className="org-name">{c.data.label}</span>
                        <span className="dim mono small">{c.data.name}</span>
                      </label>
                    ))}
                  </div>
                </div>

                {(!!org.superior || org.subordinates.length > 0 || org.peers.length > 0) && (
                  <div className="hint-box">
                    在代码里可以用 <code className="mono">ctx.superior</code> /
                    <code className="mono"> ctx.subordinates</code> /
                    <code className="mono"> ctx.peers</code> 拿到这些关系，
                    用 <code className="mono">ctx.delegate(名字, 任务)</code> 把活派给下级。
                  </div>
                )}
              </>
            )}

            <div className="dim small" style={{ margin: '14px 0 8px', letterSpacing: 0.4 }}>
              节点参数
            </div>
            {(def?.params?.length || 0) === 0 && (
              <div className="hint-box">这个节点没有可调参数，逻辑全在「代码逻辑」里。</div>
            )}
            {(def?.params || []).map((p) => (
              <ParamField
                key={p.key}
                def={p}
                value={data.params?.[p.key]}
                onChange={(v) =>
                  updateNode(node.id, { params: { ...(data.params || {}), [p.key]: v } })
                }
              />
            ))}

            <div className="hint-box" style={{ marginTop: 14 }}>
              节点类型 <code className="mono">{data.kind}</code>
              <br />
              输出端口：{(def?.outputs || ['out']).join(' / ')}
              <br />
              保存后会写入 <code className="mono">projects/{canvas?.slug}/nodes/{data.name}.py</code>
            </div>
          </>
        ) : (
          <>
            <div className="row" style={{ marginBottom: 8 }}>
              <span className="badge">{data.language === 'markdown' ? 'Markdown / Skill' : 'Python'}</span>
              <div style={{ flex: 1 }} />
              <button
                className="sm"
                onClick={() =>
                  updateNode(node.id, { code: (def as any)?.default_code || '' })
                }
                title="用该节点类型的默认模板覆盖当前代码"
              >
                恢复默认模板
              </button>
            </div>
            <CodeEditor
              value={data.code}
              language={data.language}
              height={430}
              onChange={(v) => updateNode(node.id, { code: v })}
            />
            <div className="hint-box">
              这段代码就是运行时的真实逻辑，签名固定为 <code className="mono">run(ctx)</code>。
              ctx 提供 llm / agent / tool / http / search / skill / remember / retrieve 等能力，
              详见项目里的 <code className="mono">runtime_sdk.py</code>。
            </div>
          </>
        )}
      </div>

      <div className="inspector-foot">
        <button className="sm" onClick={() => duplicateNode(node.id)}>
          复制
        </button>
        <button className="sm danger" onClick={() => removeNode(node.id)}>
          删除
        </button>
        <div style={{ flex: 1 }} />
        <span className="dim small">改动会在点「保存」后落盘</span>
      </div>

      {showModel && <NodeModelModal nodeId={node.id} onClose={() => setShowModel(false)} />}
    </aside>
  )
}
