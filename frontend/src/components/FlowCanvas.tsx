import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Background,
  BackgroundVariant,
  Controls,
  MarkerType,
  MiniMap,
  ReactFlow,
  useReactFlow,
  type NodeMouseHandler,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import AgentNode from './AgentNode'
import { ContextMenu, NodePicker } from './ContextMenu'
import { useStore } from '../store'

const nodeTypes = { agent: AgentNode }

type MenuState =
  | null
  | { kind: 'pane'; x: number; y: number; flow: { x: number; y: number } }
  | { kind: 'node'; x: number; y: number; nodeId: string }

export default function FlowCanvas() {
  const nodes = useStore((s) => s.nodes)
  const edges = useStore((s) => s.edges)
  const onNodesChange = useStore((s) => s.onNodesChange)
  const onEdgesChange = useStore((s) => s.onEdgesChange)
  const onConnect = useStore((s) => s.onConnect)
  const setSelected = useStore((s) => s.setSelected)
  const addNode = useStore((s) => s.addNode)
  const removeNode = useStore((s) => s.removeNode)
  const duplicateNode = useStore((s) => s.duplicateNode)
  const updateNode = useStore((s) => s.updateNode)
  const canvas = useStore((s) => s.canvas)
  const meta = useStore((s) => s.meta)
  const setViewport = useStore((s) => s.setViewport)

  const { screenToFlowPosition, fitView } = useReactFlow()
  const [menu, setMenu] = useState<MenuState>(null)
  const setInspectorTab = useStore((s) => s.setInspectorTab)
  const canvasId = canvas?.id

  // 切换画布后自动把整张图放进视野
  useEffect(() => {
    if (!canvasId) return
    const timer = setTimeout(() => {
      try {
        fitView({ padding: 0.16, minZoom: 0.28, maxZoom: 1.05, duration: 220 })
      } catch {
        /* 画布还没初始化完，忽略 */
      }
    }, 180)
    return () => clearTimeout(timer)
  }, [canvasId, fitView])

  const styledEdges = useMemo(
    () =>
      edges.map((e) => ({
        ...e,
        type: e.type || 'smoothstep',
        markerEnd: (e.markerEnd as any) || {
          type: MarkerType.ArrowClosed,
          width: 18,
          height: 18,
          color: '#6b7fa5',
        },
        style: { stroke: '#55688b', strokeWidth: 2, ...(e.style || {}) },
        labelStyle: { fill: '#9db0d0', fontSize: 10, fontFamily: 'sans-serif' },
        labelBgStyle: { fill: '#121828', fillOpacity: 0.9 },
        labelBgPadding: [4, 2] as [number, number],
        labelBgBorderRadius: 4,
      })),
    [edges],
  )

  const handlePaneContextMenu = useCallback(
    (event: React.MouseEvent | MouseEvent) => {
      event.preventDefault()
      const e = event as MouseEvent
      const flow = screenToFlowPosition({ x: e.clientX, y: e.clientY })
      setMenu({ kind: 'pane', x: e.clientX, y: e.clientY, flow })
    },
    [screenToFlowPosition],
  )

  const handleNodeContextMenu: NodeMouseHandler = useCallback(
    (event, node) => {
      event.preventDefault()
      setSelected(node.id)
      setMenu({ kind: 'node', x: event.clientX, y: event.clientY, nodeId: node.id })
    },
    [setSelected],
  )

  const frameworkLabel =
    meta?.frameworks.find((f) => f.id === canvas?.framework)?.label || canvas?.framework || '-'

  return (
    <div className="canvas-area">
      <ReactFlow
        nodes={nodes}
        edges={styledEdges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onNodeClick={(_, node) => setSelected(node.id)}
        onPaneClick={() => {
          setSelected(null)
          setMenu(null)
        }}
        onNodeContextMenu={handleNodeContextMenu}
        onPaneContextMenu={handlePaneContextMenu}
        onMoveEnd={(_, viewport) => setViewport(viewport)}
        fitView
        fitViewOptions={{ padding: 0.16, minZoom: 0.28, maxZoom: 1.05 }}
        minZoom={0.12}
        maxZoom={2.2}
        deleteKeyCode={['Delete', 'Backspace']}
        zoomOnDoubleClick={false}
        proOptions={{ hideAttribution: true }}
        connectionLineStyle={{ stroke: '#22d3ee', strokeWidth: 2 }}
        defaultEdgeOptions={{ type: 'smoothstep' }}
        snapToGrid
        snapGrid={[16, 16]}
      >
        <Background variant={BackgroundVariant.Dots} gap={22} size={1} color="#1d2740" />
        <Controls showInteractive={false} />
        <MiniMap
          pannable
          zoomable
          nodeColor={(n) => {
            const def = meta?.nodes.find((x) => x.kind === (n.data as any)?.kind)
            return def?.color || '#465a85'
          }}
          maskColor="rgba(8,12,20,0.72)"
          style={{
            width: 148,
            height: 102,
            background: '#0d1220',
            border: '1px solid #253352',
            borderRadius: 8,
          }}
        />
      </ReactFlow>

      <div className="canvas-hud">
        <div className="hud-chip">{frameworkLabel}</div>
        <div className="hud-chip">
          {nodes.length} 个节点 · {edges.length} 条连线
        </div>
        <div className="hud-chip dim">右键画布新增节点 · 右键节点编辑</div>
      </div>

      {nodes.length === 0 && (
        <div className="empty-state">
          <div>
            <div style={{ fontSize: 30, marginBottom: 8 }}>◇</div>
            画布是空的，右键任意位置新增第一个节点
          </div>
        </div>
      )}

      {menu?.kind === 'pane' && (
        <ContextMenu x={menu.x} y={menu.y} onClose={() => setMenu(null)} minWidth={288}>
          <NodePicker
            onPick={(kind) => {
              addNode(kind, menu.flow)
              setMenu(null)
            }}
          />
        </ContextMenu>
      )}

      {menu?.kind === 'node' && (
        <ContextMenu x={menu.x} y={menu.y} onClose={() => setMenu(null)} minWidth={216}>
          <div className="group-title" style={{ padding: '4px 9px 6px' }}>
            {nodes.find((n) => n.id === menu.nodeId)?.data.label}
          </div>
          <div
            className="ctx-item"
            onClick={() => {
              setInspectorTab('code')
              setSelected(menu.nodeId)
              setMenu(null)
            }}
          >
            <span className="ico">&lt;/&gt;</span> 编辑代码逻辑
          </div>
          <div
            className="ctx-item"
            onClick={() => {
              setInspectorTab('props')
              setSelected(menu.nodeId)
              setMenu(null)
            }}
          >
            <span className="ico">✎</span> 编辑属性与参数
          </div>
          <div
            className="ctx-item"
            onClick={() => {
              const node = nodes.find((n) => n.id === menu.nodeId)
              if (node) {
                const name = window.prompt('节点标识（会作为代码文件名）', node.data.name)
                if (name && name.trim()) updateNode(node.id, { name: name.trim() })
              }
              setMenu(null)
            }}
          >
            <span className="ico">🏷</span> 重命名标识
          </div>
          <div
            className="ctx-item"
            onClick={() => {
              duplicateNode(menu.nodeId)
              setMenu(null)
            }}
          >
            <span className="ico">⧉</span> 复制节点
          </div>
          <div className="menu-sep" />
          <div
            className="ctx-item"
            style={{ color: 'var(--err)' }}
            onClick={() => {
              removeNode(menu.nodeId)
              setMenu(null)
            }}
          >
            <span className="ico">🗑</span> 删除节点
          </div>
        </ContextMenu>
      )}
    </div>
  )
}
