import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useStore } from '../store'
import type { NodeDoc, NodeTypeDef } from '../types'
import NodeDocCard from './NodeDocCard'

export function ContextMenu({
  x,
  y,
  onClose,
  children,
  minWidth = 220,
}: {
  x: number
  y: number
  onClose: () => void
  children: ReactNode
  minWidth?: number
}) {
  const ref = useRef<HTMLDivElement>(null)
  const [pos, setPos] = useState({ left: x, top: y })

  // 贴边修正：菜单内容变化（搜索过滤）时也要重新测量，保证始终完整落在视口内
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const update = () => {
      const rect = el.getBoundingClientRect()
      const left = Math.max(8, Math.min(x, window.innerWidth - rect.width - 12))
      const top =
        y + rect.height + 12 > window.innerHeight
          ? Math.max(8, window.innerHeight - rect.height - 12)
          : y
      setPos((prev) => (prev.left === left && prev.top === top ? prev : { left, top }))
    }
    update()
    let ro: ResizeObserver | null = null
    if (typeof ResizeObserver !== 'undefined') {
      ro = new ResizeObserver(update)
      ro.observe(el)
    }
    return () => ro?.disconnect()
  }, [x, y])

  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as globalThis.Node)) onClose()
    }
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    const timer = setTimeout(() => document.addEventListener('mousedown', onDown), 0)
    document.addEventListener('keydown', onKey)
    return () => {
      clearTimeout(timer)
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [onClose])

  const style = useMemo(
    () => ({ left: pos.left, top: pos.top, minWidth }),
    [pos.left, pos.top, minWidth],
  )

  return (
    <div className="ctx-menu" ref={ref} style={style} onContextMenu={(e) => e.preventDefault()}>
      {children}
    </div>
  )
}

export function NodePicker({ onPick }: { onPick: (kind: string) => void }) {
  const meta = useStore((s) => s.meta)
  const [q, setQ] = useState('')
  // 悬停时在右侧弹出的说明卡片
  const [hover, setHover] = useState<{
    kind: string
    label: string
    doc?: NodeDoc
    top: number
    left: number
  } | null>(null)

  const categories = meta?.categories ?? []
  const grouped = useMemo(() => {
    const nodes = (meta?.nodes ?? []).filter((n: NodeTypeDef) => {
      if (!q.trim()) return true
      const t = q.trim().toLowerCase()
      return (
        n.label.toLowerCase().includes(t) ||
        n.kind.toLowerCase().includes(t) ||
        n.description.toLowerCase().includes(t)
      )
    })
    return categories
      .map((c) => ({ cat: c, items: nodes.filter((n) => n.category === c.id) }))
      .filter((g) => g.items.length > 0)
  }, [meta, q, categories])

  const showDoc = (e: React.MouseEvent<HTMLDivElement>, n: NodeTypeDef) => {
    if (!n.doc) return
    const r = e.currentTarget.getBoundingClientRect()
    const width = 300
    const left = r.right + 12 + width > window.innerWidth ? r.left - width - 12 : r.right + 12
    const top = Math.max(12, Math.min(r.top - 8, window.innerHeight - 320))
    setHover({ kind: n.kind, label: n.label, doc: n.doc, top, left })
  }

  return (
    <>
      <div className="ctx-search">
        <input
          autoFocus
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="搜索节点：tool / observation / 记忆 / 循环…"
        />
      </div>
      {grouped.length === 0 && (
        <div className="ctx-item dim" style={{ cursor: 'default' }}>
          没有匹配的节点
        </div>
      )}
      {grouped.map((g) => (
        <div key={g.cat.id}>
          <div className="ctx-cat">
            <span
              style={{
                width: 7,
                height: 7,
                borderRadius: 4,
                background: g.cat.color,
                display: 'inline-block',
              }}
            />
            {g.cat.label}
          </div>
          {g.items.map((n) => (
            <div
              key={n.kind}
              className="ctx-item"
              onClick={() => onPick(n.kind)}
              onMouseEnter={(e) => showDoc(e, n)}
              onMouseLeave={() => setHover(null)}
            >
              <span className="ico" style={{ color: n.color }}>
                {n.icon}
              </span>
              <span>{n.label}</span>
              <span className="hint">{n.kind}</span>
            </div>
          ))}
        </div>
      ))}

      {hover && (
        <div className="node-doc" style={{ position: 'fixed', top: hover.top, left: hover.left, width: 300 }}>
          <NodeDocCard label={hover.label} kind={hover.kind} doc={hover.doc} />
        </div>
      )}
    </>
  )
}
