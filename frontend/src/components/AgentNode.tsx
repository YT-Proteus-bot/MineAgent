import { Handle, Position, type NodeProps } from '@xyflow/react'
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

export default function AgentNode({ id, data, selected }: NodeProps<AgentNodeType>) {
  const meta = useStore((s) => s.meta)
  const setSelected = useStore((s) => s.setSelected)
  const setInspectorTab = useStore((s) => s.setInspectorTab)
  const def = meta?.nodes.find((n) => n.kind === data.kind)
  const outputs = def?.outputs ?? ['out']
  const color = def?.color ?? '#8b5cf6'
  const icon = def?.icon ?? '◆'
  const status = (data.status || 'idle') as string
  const isAgent = isAgentKind(data.kind)
  const mode = ((data.params || {}).mode as string) || 'react'
  const rawOrg = (data.org || {}) as Partial<AgentOrg>
  const org: AgentOrg = {
    superior: rawOrg.superior || '',
    subordinates: rawOrg.subordinates || [],
    peers: rawOrg.peers || [],
  }
  const nodeModel = (data.model || {}) as Record<string, any>

  return (
    <div
      className={`agent-node${selected ? ' selected' : ''} status-${status}`}
      onDoubleClick={() => {
        setSelected(id)
        setInspectorTab('code')
      }}
    >
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
    </div>
  )
}
