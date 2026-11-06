import { useState } from 'react'
import { Handle, NodeResizer, Position, type NodeProps } from '@xyflow/react'
import { useStore } from '../store'
import NodeDocCard from './NodeDocCard'
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
  const highlighted = useStore((s) => s.highlightedNodeIds.includes(id))
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
      }${resized ? ' resized' : ''}${highlighted ? ' highlighted' : ''}`}
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
      {status === 'running' && <div className="node-running-badge">运行中</div>}
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

      {/* 错误出口：节点失败（且失败策略选了「走 error 连线」）时走这条边 */}
      <Handle
        type="source"
        position={Position.Right}
        id="error"
        className="handle-error"
        title="错误出口（失败时走这条线）"
        style={{ right: -5, top: 'calc(100% - 16px)' }}
      />

      {hovered && !dragging && (
        <div className="node-tip">
          <NodeDocCard
            label={data.label}
            kind={data.kind}
            doc={def?.doc}
            footer={
              <>
                {isAgent ? `${MODE_LABEL[mode] || mode} · 最多 ${data.params?.max_steps ?? 6} 步` : null}
                {isAgent ? ' · ' : ''}
                出口 {outputs.map((o) => BRANCH_LABEL[o] || o).join(' / ')}
                <br />
                双击打开代码 · 右键查看与编辑
              </>
            }
          />
        </div>
      )}
    </div>
  )
}
