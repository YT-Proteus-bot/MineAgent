import { useMemo, useRef } from 'react'

interface Props {
  value: string
  onChange: (v: string) => void
  language?: string
  height?: number | string
  readOnly?: boolean
}

export default function CodeEditor({ value, onChange, language = 'python', height = 380, readOnly }: Props) {
  const areaRef = useRef<HTMLTextAreaElement>(null)
  const gutterRef = useRef<HTMLDivElement>(null)
  const lines = useMemo(() => (value || '').split('\n'), [value])

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key !== 'Tab' || readOnly) return
    e.preventDefault()
    const ta = e.currentTarget
    const start = ta.selectionStart
    const end = ta.selectionEnd
    const next = value.slice(0, start) + '    ' + value.slice(end)
    onChange(next)
    requestAnimationFrame(() => {
      ta.selectionStart = ta.selectionEnd = start + 4
    })
  }

  return (
    <div className="code-editor" style={{ height }}>
      <div className="code-gutter" ref={gutterRef}>
        {lines.map((_, i) => (
          <div key={i}>{i + 1}</div>
        ))}
      </div>
      <textarea
        className="code-area"
        ref={areaRef}
        value={value}
        readOnly={readOnly}
        spellCheck={false}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={handleKeyDown}
        onScroll={() => {
          if (gutterRef.current && areaRef.current) {
            gutterRef.current.scrollTop = areaRef.current.scrollTop
          }
        }}
        placeholder={language === 'markdown' ? '# 在这里粘贴 skill.md 的内容' : '# 在这里写节点逻辑'}
      />
    </div>
  )
}
