import {
  BaseEdge,
  EdgeLabelRenderer,
  getBezierPath,
  useStore,
  type EdgeProps,
} from '@xyflow/react'

/** 同源同目标的多条边之间的错开间距（px） */
const SPREAD = 26

/**
 * 画布连线。
 * - 同一对节点之间有多条边时，按索引上下错开，不会叠成一条；
 * - 循环回边由 FlowCanvas 统一改成虚线，避免和正向流程混在一起。
 */
export default function AgentEdge({
  id,
  source,
  target,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  markerEnd,
  style,
  label,
  selected,
}: EdgeProps) {
  const parallel = useStore((s) =>
    s.edges.filter((e) => e.source === source && e.target === target),
  )
  const index = Math.max(0, parallel.findIndex((e) => e.id === id))
  const spread =
    parallel.length > 1 ? (index - (parallel.length - 1) / 2) * SPREAD : 0

  const [path, labelX, labelY] = getBezierPath({
    sourceX,
    sourceY: sourceY + spread,
    sourcePosition,
    targetX,
    targetY: targetY + spread,
    targetPosition,
    curvature: 0.32,
  })

  return (
    <>
      <BaseEdge
        id={id}
        path={path}
        markerEnd={markerEnd}
        style={{
          ...style,
          ...(selected ? { strokeWidth: 2.6 } : null),
        }}
      />
      {label ? (
        <EdgeLabelRenderer>
          <div
            className="edge-chip"
            style={{
              position: 'absolute',
              transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)`,
              pointerEvents: 'none',
            }}
          >
            {label as string}
          </div>
        </EdgeLabelRenderer>
      ) : null}
    </>
  )
}
