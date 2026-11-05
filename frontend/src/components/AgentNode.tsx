import { useState } from 'react'
import { Handle, NodeResizer, Position, type NodeProps } from '@xyflow/react'
import { useStore } from '../store'
import { isAgentKind, type AgentNode as AgentNodeType, type AgentOrg } from '../types'

const BRANCH_LABEL: Record<string, string> = {
  out: '输出',
  true: '是',
  false: '否',
  loop: '继续',
  exit: '退出',
  yes: '是',
  no: '否',
  approve: '通过',
  reject: '拒绝',
}

const MODE_LABEL: Record<string, string> = {
  react: 'ReAct',
  plan_execute: 'Plan',
  goal: 'Goal',
  reflexion: 'Reflexion',
  tool_call: 'ToolCall',
  simple: 'Simple',
}

export default function AgentNode({ id, data, selected, dragging }: NodeProps<AgentNodeType>) {
  const meta = useStore((s) => s.meta)
  const setSelected = useStore((s) => s.setSelected)
  const setInspectorTab = useStore((s) => s.setInspectorTab)
  const def = meta?.nodes.find((n) => n.kind === data.kind)
  const outputs = def?.outputs ?? ['out']
  const color = def?.color ?? '#8b5cf6'
  const icon = def?.icon ?? '◆'
  const status = (data.status || 'idle') as string
  const violated = useStore((s) => s.violatedNodeIds.includes(id))
  const isAgent = isAgentKind(data.kind)
  const mode = ((data.params || {}).mode as string) || 'react'
  const rawOrg = (data.org || {}) as Partial<AgentOrg>
  const org: AgentOrg = {
    superior: rawOrg.superior || '',
    subordinates: rawOrg.subordinates || [],
    peers: rawOrg.peers || [],
  }
  const nodeModel = (data.model || {}) as Record<string, any>
  // 注意：NodeProps 的 width/height 是测量值，这里要用用户拖出来的显式尺寸
  const resized = useStore((s) => {
    const n = s.nodes.find((x) => x.id === id)
    return !!n && (Number(n.width) > 0 || Number(n.height) > 0)
  })
  const openNodePanel = useStore((s) => s.openNodePanel)
  const [hovered, setHovered] = useState(false)

  const paramEntries = Object.entries(data.params || {})
    .filter(([, v]) => v !== '' && v !== null && v !== undefined && !(Array.isArray(v) && !v.length))
    .slice(0, 3)

  return (
    <div
      className={`agent-node${selected ? ' selected' : ''} status-${status}${
        violated ? ' violated' : ''
      }${resized ? ' resized' : ''}`}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onDoubleClick={() => openNodePanel(id, 'code')}
    >
      <NodeResizer
        minWidth={190}
        minHeight={84}
        isVisible={selected}
        lineClassName="node-resize-line"
        handleClassName="node-resize-handle"
      />
      <Handle type="target" position={Position.Left} id="in" style={{ left: -5 }} />
      <div className="node-head">
        <div className="node-icon" style={{ background: color }}>
          {icon}
        </div>
        <div className="node-label" title={data.label}>
          {data.label}
        </div>
        <div className={`node-dot ${status}`} />
      </div>
      <div className="node-body">
        <div className="node-name" title={data.name}>
          {data.name}
        </div>
        <div className="node-desc">{data.description}</div>
        {isAgent && (
          <div className="row" style={{ gap: 4, marginTop: 2, flexWrap: 'wrap' }}>
            <span className="node-mode" title="推理模式">
              {MODE_LABEL[mode] || mode}
            </span>
            {org.subordinates.length > 0 && (
              <span className="node-org" title="下级 agent 数">
                ↓{org.subordinates.length}
              </span>
            )}
            {org.peers.length > 0 && (
              <span className="node-org" title="平级 agent 数">
                ↕{org.peers.length}
              </span>
            )}
            {org.superior && (
              <span className="node-org" title="有上级 agent">
                ↑
              </span>
            )}
            {nodeModel.has_key && (
              <span className="node-key" title="使用独立 API Key">
                KEY
              </span>
            )}
          </div>
        )}
        {outputs.length > 1 && (
          <div className="row" style={{ gap: 4, marginTop: 2 }}>
            {outputs.map((o) => (
              <span key={o} className="badge" style={{ padding: '0 5px' }}>
                {BRANCH_LABEL[o] || o}
              </span>
            ))}
          </div>
        )}
      </div>
      <div className="node-foot">
        <span className="node-kind">{data.kind}</span>
        {typeof data.durationMs === 'number' && <span>{data.durationMs}ms</span>}
      </div>
      {outputs.map((o, i) => (
        <Handle
          key={o}
          type="source"
          position={Position.Right}
          id={o}
          title={BRANCH_LABEL[o] || o}
          style={{
            right: -5,
            top: `${outputs.length === 1 ? 50 : 34 + i * (64 / Math.max(outputs.length - 1, 1))}%`,
          }}
        />
      ))}

      {hovered && !dragging && (
        <div className="node-tip">
          <div className="tip-title">{data.label}</div>
          <div className="tip-name">{data.name}</div>
          {data.description && <div className="tip-desc">{data.description}</div>}
          <div className="tip-row">
            <span className="tip-key">类型</span>
            <span className="tip-val">{def?.label || data.kind}（{data.kind}）</span>
          </div>
          {isAgent && (
            <div className="tip-row">
              <span className="tip-key">模式</span>
              <span className="tip-val">
                {MODE_LABEL[mode] || mode}
                {nodeModel.model ? ` · ${nodeModel.model}` : ''}
                {nodeModel.has_key ? ' · 独立 Key' : ''}
              </span>
            </div>
          )}
          {isAgent && (org.superior || org.subordinates.length > 0 || org.peers.length > 0) && (
            <div className="tip-row">
              <span className="tip-key">组织</span>
              <span className="tip-val">
                {org.superior ? '有上级' : '顶层'}
                {org.subordinates.length > 0 ? ` · 下级 ${org.subordinates.length}` : ''}
                {org.peers.length > 0 ? ` · 平级 ${org.peers.length}` : ''}
              </span>
            </div>
          )}
          {paramEntries.length > 0 && (
            <div className="tip-row">
              <span className="tip-key">参数</span>
              <span className="tip-val">
                {paramEntries
                  .map(([k, v]) => `${k}=${String(v).slice(0, 24)}`)
                  .join('，')}
              </span>
            </div>
          )}
          <div className="tip-row">
            <span className="tip-key">出口</span>
            <span className="tip-val">{outputs.map((o) => BRANCH_LABEL[o] || o).join(' / ')}</span>
          </div>
          <div className="tip-hint">双击打开代码 · 右键查看与编辑</div>
        </div>
      )}
    </div>
  )
}
