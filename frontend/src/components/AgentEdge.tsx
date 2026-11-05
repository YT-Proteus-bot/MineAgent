import { useMemo, useState } from 'react'
import { BaseEdge, EdgeLabelRenderer, useReactFlow, type EdgeProps } from '@xyflow/react'
import { useStore } from '../store'

/** 同源同目标的多条边之间的错开间距（px） */
const SPREAD = 26

function bezierPoint(
  x0: number, y0: number, x1: number, y1: number,
  x2: number, y2: number, x3: number, y3: number, t = 0.5,
) {
  const mt = 1 - t
  const a = mt * mt * mt
  const b = 3 * mt * mt * t
  const c = 3 * mt * t * t
  const d = t * t * t
  return { x: a * x0 + b * x1 + c * x2 + d * x3, y: a * y0 + b * y1 + c * y2 + d * y3 }
}

/**
 * 画布连线。
 * - 同一对节点之间有多条边时按索引上下错开；
 * - 可以按住线中间的小圆点拖动，调整这根线的弯曲走向（不改变 source / target）；
 * - 循环回边的虚线样式由 FlowCanvas 统一设置。
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
  // 注意：selector 必须返回稳定引用，不能在里面 filter（会每次生成新数组 → 无限渲染）
  const allEdges = useStore((s) => s.edges)
  const parallel = useMemo(
    () => allEdges.filter((e) => e.source === source && e.target === target),
    [allEdges, source, target],
  )
  const updateEdgeData = useStore((s) => s.updateEdgeData)
  const { screenToFlowPosition } = useReactFlow()
  const [hovered, setHovered] = useState(false)

  const index = Math.max(0, parallel.findIndex((e) => e.id === id))
  const spread = parallel.length > 1 ? (index - (parallel.length - 1) / 2) * SPREAD : 0
  const offset = (data?.controlOffset as { x: number; y: number }) || { x: 0, y: 0 }

  const geometry = useMemo(() => {
    const sy = sourceY + spread
    const ty = targetY + spread
    const dx = Math.max(70, Math.abs(targetX - sourceX) * 0.45)
    const dir = targetX >= sourceX ? 1 : -1
    const c1x = sourceX + dx * dir + offset.x
    const c1y = sy + offset.y
    const c2x = targetX - dx * dir + offset.x
    const c2y = ty + offset.y
    const path = `M ${sourceX},${sy} C ${c1x},${c1y} ${c2x},${c2y} ${targetX},${ty}`
    const mid = bezierPoint(sourceX, sy, c1x, c1y, c2x, c2y, targetX, ty)
    return { path, mid }
  }, [sourceX, sourceY, targetX, targetY, offset.x, offset.y, spread])

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
      {/* 悬停热区：让整条线都好点中 */}
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
