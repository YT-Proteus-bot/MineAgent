import { Handle, Position, type NodeProps } from '@xyflow/react'
import { useStore } from '../store'
import type { AgentNode as AgentNodeType } from '../types'

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

export default function AgentNode({ id, data, selected }: NodeProps<AgentNodeType>) {
  const meta = useStore((s) => s.meta)
  const setSelected = useStore((s) => s.setSelected)
  const setInspectorTab = useStore((s) => s.setInspectorTab)
  const def = meta?.nodes.find((n) => n.kind === data.kind)
  const outputs = def?.outputs ?? ['out']
  const color = def?.color ?? '#8b5cf6'
  const icon = def?.icon ?? '◆'
  const status = (data.status || 'idle') as string

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
