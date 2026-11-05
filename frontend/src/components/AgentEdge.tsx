import { useMemo, useState } from 'react'
import { BaseEdge, EdgeLabelRenderer, useReactFlow, type EdgeProps } from '@xyflow/react'
import { useStore } from '../store'

/** 同源同目标的多条边之间的错开间距（px） */
const SPREAD = 26
/** 连线与节点之间保留的间隙 */
const NODE_PAD = 12
/** 绕行时离开节点群边缘的距离 */
const DETOUR_GAP = 46

export interface Rect {
  x: number
  y: number
  w: number
  h: number
}

interface Pt {
  x: number
  y: number
}

function pointInRect(p: Pt, r: Rect, pad: number): boolean {
  return p.x >= r.x - pad && p.x <= r.x + r.w + pad && p.y >= r.y - pad && p.y <= r.y + r.h + pad
}

/** 线段是否穿过任一矩形（采样检测，节点少的时候足够用且便宜） */
function segmentHits(
  a: Pt,
  b: Pt,
  rects: Rect[],
  pad: number,
  endpoints: Pt[],
  endpointSlack: number,
): boolean {
  const minX = Math.min(a.x, b.x)
  const maxX = Math.max(a.x, b.x)
  const minY = Math.min(a.y, b.y)
  const maxY = Math.max(a.y, b.y)
  const steps = 14
  for (let i = 0; i <= steps; i++) {
    const t = i / steps
    const p = { x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t }
    // 端点附近（连线必然贴着 handle）不算越界
    if (endpoints.some((c) => Math.hypot(p.x - c.x, p.y - c.y) < endpointSlack)) continue
    for (const r of rects) {
      // 粗筛：包围盒不相交就不用逐点判断
      if (maxX < r.x - pad || minX > r.x + r.w + pad) continue
      if (maxY < r.y - pad || minY > r.y + r.h + pad) continue
      if (pointInRect(p, r, pad)) return true
    }
  }
  return false
}

function polylineHits(points: Pt[], rects: Rect[], pad: number): boolean {
  const ends = [points[0], points[points.length - 1]]
  for (let i = 0; i < points.length - 1; i++) {
    if (segmentHits(points[i], points[i + 1], rects, pad, ends, 14)) return true
  }
  return false
}

/** 把折线画成带圆角的路径 */
function roundedPath(points: Pt[], radius = 10): string {
  if (points.length < 2) return ''
  if (points.length === 2) {
    return `M ${points[0].x},${points[0].y} L ${points[1].x},${points[1].y}`
  }
  let d = `M ${points[0].x},${points[0].y}`
  for (let i = 1; i < points.length - 1; i++) {
    const prev = points[i - 1]
    const cur = points[i]
    const next = points[i + 1]
    const d1 = Math.hypot(cur.x - prev.x, cur.y - prev.y) || 1
    const d2 = Math.hypot(next.x - cur.x, next.y - cur.y) || 1
    const r = Math.min(radius, d1 / 2, d2 / 2)
    const p1 = { x: cur.x - ((cur.x - prev.x) / d1) * r, y: cur.y - ((cur.y - prev.y) / d1) * r }
    const p2 = { x: cur.x + ((next.x - cur.x) / d2) * r, y: cur.y + ((next.y - cur.y) / d2) * r }
    d += ` L ${p1.x},${p1.y} Q ${cur.x},${cur.y} ${p2.x},${p2.y}`
  }
  const last = points[points.length - 1]
  d += ` L ${last.x},${last.y}`
  return d
}

function bezierPath(s: Pt, t: Pt, curvature = 0.45): { path: string; mid: Pt } {
  const dx = Math.max(70, Math.abs(t.x - s.x) * curvature)
  const dir = t.x >= s.x ? 1 : -1
  const c1 = { x: s.x + dx * dir, y: s.y }
  const c2 = { x: t.x - dx * dir, y: t.y }
  const path = `M ${s.x},${s.y} C ${c1.x},${c1.y} ${c2.x},${c2.y} ${t.x},${t.y}`
  const mid = {
    x: (s.x + 3 * c1.x + 3 * c2.x + t.x) / 8,
    y: (s.y + 3 * c1.y + 3 * c2.y + t.y) / 8,
  }
  return { path, mid }
}

/**
 * 挑选一条不压节点的走线。
 * 优先直线；被挡住就从上方或下方绕过去；实在绕不开就用交叉最少的方案。
 */
export function routeAround(s: Pt, t: Pt, obstacles: Rect[]): { points: Pt[]; direct: boolean } {
  if (!obstacles.length) return { points: [s, t], direct: true }

  const direct = [s, t]
  if (!polylineHits(direct, obstacles, NODE_PAD)) return { points: direct, direct: true }

  const gap = 28
  const topY = Math.min(...obstacles.map((o) => o.y)) - DETOUR_GAP
  const bottomY = Math.max(...obstacles.map((o) => o.y + o.h)) + DETOUR_GAP

  const over = [
    s,
    { x: s.x + gap, y: s.y },
    { x: s.x + gap, y: topY },
    { x: t.x - gap, y: topY },
    { x: t.x - gap, y: t.y },
    t,
  ]
  if (!polylineHits(over, obstacles, NODE_PAD)) return { points: over, direct: false }

  const under = [
    s,
    { x: s.x + gap, y: s.y },
    { x: s.x + gap, y: bottomY },
    { x: t.x - gap, y: bottomY },
    { x: t.x - gap, y: t.y },
    t,
  ]
  if (!polylineHits(under, obstacles, NODE_PAD)) return { points: under, direct: false }

  // 都不行：再试绕到两侧，最后按长度选短的那条
  const rightX = Math.max(s.x, t.x, ...obstacles.map((o) => o.x + o.w)) + DETOUR_GAP
  const viaRight = [
    s,
    { x: s.x + gap, y: s.y },
    { x: rightX, y: s.y },
    { x: rightX, y: t.y },
    { x: t.x + gap, y: t.y },
    t,
  ]
  if (!polylineHits(viaRight, obstacles, NODE_PAD)) return { points: viaRight, direct: false }

  const len = (pts: Pt[]) =>
    pts.reduce(
      (acc, p, i) => (i === 0 ? 0 : acc + Math.hypot(p.x - pts[i - 1].x, p.y - pts[i - 1].y)),
      0,
    )
  const scored = [
    { pts: over, hits: countHits(over, obstacles) },
    { pts: under, hits: countHits(under, obstacles) },
    { pts: viaRight, hits: countHits(viaRight, obstacles) },
  ].sort((a, b) => a.hits - b.hits || len(a.pts) - len(b.pts))
  return { points: scored[0].pts, direct: false }
}

function countHits(points: Pt[], rects: Rect[]): number {
  let hits = 0
  const ends = [points[0], points[points.length - 1]]
  for (let i = 0; i < points.length - 1; i++) {
    const a = points[i]
    const b = points[i + 1]
    for (let k = 0; k <= 10; k++) {
      const t = k / 10
      const p = { x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t }
      if (ends.some((c) => Math.hypot(p.x - c.x, p.y - c.y) < 14)) continue
      if (rects.some((r) => pointInRect(p, r, NODE_PAD))) hits++
    }
  }
  return hits
}

/**
 * 画布连线。
 * - 自动绕开其它节点，不会压在节点上，也不会被节点盖住；
 * - 手动拖动过（有 controlOffset）之后以手动走向为准；
 * - 同一对节点之间多条边仍会错开；回边虚线样式由 FlowCanvas 统一设置。
 */
export default function AgentEdge({
  id,
  source,
  target,
  sourceX,
  sourceY,
  targetX,
  targetY,
  markerEnd,
  style,
  label,
  selected,
  data,
}: EdgeProps) {
  // selector 必须返回稳定引用：不能在里面 filter
  const allEdges = useStore((s) => s.edges)
  const allNodes = useStore((s) => s.nodes)
  const updateEdgeData = useStore((s) => s.updateEdgeData)
  const { screenToFlowPosition } = useReactFlow()
  const [hovered, setHovered] = useState(false)

  const parallel = useMemo(
    () => allEdges.filter((e) => e.source === source && e.target === target),
    [allEdges, source, target],
  )
  const index = Math.max(0, parallel.findIndex((e) => e.id === id))
  const spread = parallel.length > 1 ? (index - (parallel.length - 1) / 2) * SPREAD : 0
  const offset = (data?.controlOffset as { x: number; y: number }) || { x: 0, y: 0 }
  const manual = offset.x !== 0 || offset.y !== 0

  const obstacles = useMemo<Rect[]>(
    () =>
      allNodes.map((n) => ({
        x: n.position.x,
        y: n.position.y,
        w: Number(n.width) || n.measured?.width || 216,
        h: Number(n.height) || n.measured?.height || 92,
      })),
    [allNodes],
  )

  const geometry = useMemo(() => {
    const s = { x: sourceX, y: sourceY + spread }
    const t = { x: targetX, y: targetY + spread }
    if (manual) {
      // 用户手动拖过的线：保持他拖出来的形状
      const shiftedS = { x: s.x, y: s.y + offset.y }
      const shiftedT = { x: t.x, y: t.y + offset.y }
      const b = bezierPath(shiftedS, shiftedT)
      return { path: b.path, mid: { x: b.mid.x + offset.x, y: b.mid.y } }
    }
    const route = routeAround(s, t, obstacles)
    if (route.direct) {
      const b = bezierPath(s, t)
      return { path: b.path, mid: b.mid }
    }
    const path = roundedPath(route.points)
    const midIdx = Math.floor(route.points.length / 2)
    return { path, mid: route.points[midIdx] }
  }, [sourceX, sourceY, targetX, targetY, spread, offset.x, offset.y, manual, obstacles])

  const startDrag = (e: React.PointerEvent) => {
    e.stopPropagation()
    e.preventDefault()
    const start = screenToFlowPosition({ x: e.clientX, y: e.clientY })
    const base = { ...offset }
    document.body.style.cursor = 'grabbing'

    const onMove = (ev: PointerEvent) => {
      const p = screenToFlowPosition({ x: ev.clientX, y: ev.clientY })
      updateEdgeData(id, {
        controlOffset: { x: base.x + (p.x - start.x), y: base.y + (p.y - start.y) },
      })
    }
    const onUp = () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
      document.body.style.cursor = ''
    }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
  }

  const showHandle = selected || hovered

  return (
    <>
      <BaseEdge
        id={id}
        path={geometry.path}
        markerEnd={markerEnd}
        style={{
          ...style,
          ...(selected ? { strokeWidth: 2.8 } : null),
        }}
        interactionWidth={22}
      />
      {/* 中间那层：把连线画在节点下方，即使几何上靠得很近也不会盖住节点内容 */}
      {label || showHandle ? (
        <EdgeLabelRenderer>
          {label ? (
            <div
              className="edge-chip"
              style={{
                position: 'absolute',
                transform: `translate(-50%, -50%) translate(${geometry.mid.x}px,${geometry.mid.y}px)`,
                pointerEvents: 'none',
              }}
            >
              {label as string}
            </div>
          ) : null}
          {showHandle ? (
            <div
              className="edge-drag"
              title="按住拖动可以调整这条线的走向（不改变连接关系）"
              onPointerDown={startDrag}
              onMouseEnter={() => setHovered(true)}
              onMouseLeave={() => setHovered(false)}
              style={{
                position: 'absolute',
                transform: `translate(-50%, -50%) translate(${geometry.mid.x}px,${
                  geometry.mid.y + (label ? 22 : 0)
                }px)`,
                pointerEvents: 'all',
              }}
            >
              <span />
            </div>
          ) : null}
        </EdgeLabelRenderer>
      ) : null}
      {/* 悬停热区 */}
      <path
        d={geometry.path}
        fill="none"
        stroke="transparent"
        strokeWidth={22}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        style={{ pointerEvents: 'stroke', cursor: 'pointer' }}
      />
    </>
  )
}
