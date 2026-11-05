import type { NodeDoc } from '../types'

/**
 * 节点的说明卡片：概念 / 解释 / 用途 / 编码建议。
 * 节点悬停浮层和右键新增节点面板共用这一个。
 */
export default function NodeDocCard({
  label,
  kind,
  doc,
  footer,
}: {
  label: string
  kind: string
  doc?: NodeDoc | null
  footer?: React.ReactNode
}) {
  const d = doc || {
    concept: '一个通用处理步骤。',
    explain: '接收上游结果，处理后交给下游。',
    usage: '按需使用。',
    tips: '先确认它的输入输出格式，再决定接到哪里。',
  }
  const rows: Array<[string, string]> = [
    ['概念', d.concept],
    ['解释', d.explain],
    ['用途', d.usage],
    ['编码建议', d.tips],
  ]
  return (
    <div className="node-doc-card">
      <div className="ndc-head">
        <span className="ndc-label">{label}</span>
        <span className="ndc-kind mono">{kind}</span>
      </div>
      {rows.map(([k, v]) => (
        <div key={k} className="ndc-row">
          <span className="ndc-key">{k}</span>
          <span className="ndc-val">{v}</span>
        </div>
      ))}
      {footer ? <div className="ndc-foot">{footer}</div> : null}
    </div>
  )
}
