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
import AgentEdge from './AgentEdge'
import BackgroundPanel from './BackgroundPanel'
import ConstraintPanel from './ConstraintPanel'
import NodeModelModal from './NodeModelModal'
import { ContextMenu, NodePicker } from './ContextMenu'
import { useStore } from '../store'
import { DEFAULT_BACKGROUND, isAgentKind, usesLLM } from '../types'

const nodeTypes = { agent: AgentNode }
const edgeTypes = { agent: AgentEdge }

const BRANCH_TEXT: Record<string, string> = {
  out: '输出',
  true: '是（true）',
  false: '否（false）',
  loop: '继续（loop）',
  exit: '退出（exit）',
  yes: '是',
  no: '否',
  approve: '通过',
  reject: '拒绝',
}

type LinkerState = null | {
  source: string
  handle: string | null
  step: 'branch' | 'target'
}

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
  const openNodePanel = useStore((s) => s.openNodePanel)
  const addNode = useStore((s) => s.addNode)
  const removeNode = useStore((s) => s.removeNode)
  const duplicateNode = useStore((s) => s.duplicateNode)
  const resetNodeSize = useStore((s) => s.resetNodeSize)
  const updateNode = useStore((s) => s.updateNode)
  const canvas = useStore((s) => s.canvas)
  const meta = useStore((s) => s.meta)
  const setViewport = useStore((s) => s.setViewport)

  const { screenToFlowPosition, fitView } = useReactFlow()
  const [menu, setMenu] = useState<MenuState>(null)
  const [bgPanelOpen, setBgPanelOpen] = useState(false)
  const [modelNodeId, setModelNodeId] = useState<string | null>(null)
  const setInspectorTab = useStore((s) => s.setInspectorTab)
  const canvasId = canvas?.id
  const menuNodeKind =
    menu?.kind === 'node'
      ? nodes.find((n) => n.id === menu.nodeId)?.data.kind
      : undefined
  const menuNodeIsAgent = isAgentKind(menuNodeKind)
  // 优先用保存时扫描源码得出的结论；还没保存过才退回按节点类型判断
  const menuNode = menu?.kind === 'node' ? nodes.find((n) => n.id === menu.nodeId) : undefined
  const menuNodeDef = meta?.nodes.find((n) => n.kind === menuNodeKind)
  const menuNodeUsesLLM =
    menuNode?.data.uses_llm ?? menuNodeDef?.uses_llm ?? usesLLM(menuNodeKind)

  const constraintPanelOpen = useStore((s) => s.constraintPanelOpen)
  const setConstraintPanelOpen = useStore((s) => s.setConstraintPanelOpen)
  const validateNow = useStore((s) => s.validateNow)
  const connectNodes = useStore((s) => s.connectNodes)
  const autoLayout = useStore((s) => s.autoLayout)
  const setHighlightedNodes = useStore((s) => s.setHighlightedNodes)
  const updateEdgeData = useStore((s) => s.updateEdgeData)
  const updateEdgeEndpoint = useStore((s) => s.updateEdgeEndpoint)
  const removeEdge = useStore((s) => s.removeEdge)

  const [edgeMenu, setEdgeMenu] = useState<null | {
    x: number
    y: number
    edgeId: string
    mode: 'root' | 'source' | 'target'
  }>(null)

  const handleEdgeClick = useCallback(
    (_evt: React.MouseEvent, edge: any) => {
      setHighlightedNodes([edge.source, edge.target])
    },
    [setHighlightedNodes],
  )

  const handleEdgeContextMenu = useCallback(
    (evt: React.MouseEvent, edge: any) => {
      evt.preventDefault()
      setHighlightedNodes([edge.source, edge.target])
      setEdgeMenu({ x: evt.clientX, y: evt.clientY, edgeId: edge.id, mode: 'root' })
    },
    [setHighlightedNodes],
  )
  const [linker, setLinker] = useState<LinkerState>(null)

  const closeMenu = () => {
    setLinker(null)
    setMenu(null)
  }

  const startLinker = (nodeId: string) => {
    const node = nodes.find((n) => n.id === nodeId)
    if (!node) return
    const def = meta?.nodes.find((x) => x.kind === node.data.kind)
    const outs = def?.outputs || ['out']
    setLinker({
      source: nodeId,
      handle: outs.length === 1 ? outs[0] : null,
      step: outs.length === 1 ? 'target' : 'branch',
    })
  }

  const finishLink = (targetId: string) => {
    if (!linker) return
    connectNodes(linker.source, targetId, linker.handle || 'out')
    closeMenu()
  }

  // 编辑过程中自动复查约束（停止操作 1.3 秒后）
  useEffect(() => {
    if (!canvasId) return
    const timer = setTimeout(() => validateNow(), 1300)
    return () => clearTimeout(timer)
  }, [nodes, edges, canvasId, validateNow])

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

  // 回边（从右往左绕回去的循环线）单独用虚线，和正向流程区分开
  const nodePos = useMemo(() => new Map(nodes.map((n) => [n.id, n.position])), [nodes])

  const styledEdges = useMemo(
    () =>
      edges.map((e) => {
        const src = nodePos.get(e.source)
        const dst = nodePos.get(e.target)
        // 只有明显往回走（跨过一个节点宽度）才算回边，垂直/S 形连线不算
        const isBackEdge = !!(src && dst && dst.x < src.x - 240)
        return {
          ...e,
          type: 'agent',
          markerEnd: (e.markerEnd as any) || {
            type: MarkerType.ArrowClosed,
            width: 16,
            height: 16,
            color: isBackEdge ? '#a78bfa' : '#7c8fae',
          },
          style: {
            stroke: isBackEdge ? '#8b6fe0' : '#5b6f92',
            strokeWidth: 2,
            ...(isBackEdge ? { strokeDasharray: '6 4' } : null),
            ...(e.style || {}),
          },
        }
      }),
    [edges, nodePos],
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
      // 右键才打开右列「节点详情」
      openNodePanel(node.id, 'props')
      setMenu({ kind: 'node', x: event.clientX, y: event.clientY, nodeId: node.id })
    },
    [openNodePanel],
  )

  const frameworkLabel =
    meta?.frameworks.find((f) => f.id === canvas?.framework)?.label || canvas?.framework || '-'

  const bg = { ...DEFAULT_BACKGROUND, ...(canvas?.background || {}) }
  const imageStyle = bg.image
    ? {
        backgroundImage: `url(/api/backgrounds/${bg.image})`,
        backgroundSize:
          bg.image_fit === 'cover'
            ? 'cover'
            : bg.image_fit === 'contain'
              ? 'contain'
              : bg.image_fit === 'repeat'
                ? 'auto'
                : 'auto',
        backgroundRepeat: bg.image_fit === 'repeat' ? 'repeat' : 'no-repeat',
        backgroundPosition: 'center',
        opacity: bg.image_opacity,
      }
    : undefined

  return (
    <div className="canvas-area">
      <div
        className="canvas-bg"
        style={{ background: bg.color || 'transparent' }}
        aria-hidden
      />
      {bg.image && <div className="canvas-bg-image" style={imageStyle} aria-hidden />}

      <ReactFlow
        nodes={nodes}
        edges={styledEdges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onNodeClick={(_, node) => {
          // 单击不打开详情：节点信息看 hover 浮层，右键 / 双击才进详情面板
          setSelected(node.id)
        }}
        onEdgeClick={handleEdgeClick}
        onEdgeContextMenu={handleEdgeContextMenu}
        onPaneClick={() => {
          setSelected(null)
          setMenu(null)
          setHighlightedNodes([])
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
        // 拖线时靠近目标节点就能吸附上去，不用精确点到小圆点
        connectionRadius={48}
        proOptions={{ hideAttribution: true }}
        connectionLineStyle={{ stroke: '#22d3ee', strokeWidth: 2 }}
        defaultEdgeOptions={{ type: 'smoothstep' }}
        snapToGrid
        snapGrid={[16, 16]}
      >
        {bg.grid && (
          <Background
            variant={BackgroundVariant.Dots}
            gap={22}
            size={1}
            color={bg.grid_color || '#c9d1de'}
          />
        )}
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
        <button
          className={`hud-chip hud-btn${bgPanelOpen ? ' active' : ''}`}
          onClick={() => setBgPanelOpen((v) => !v)}
          title="调整画布底色、上传背景图"
        >
          🎨 背景
          {bg.image ? <span className="badge" style={{ padding: '0 4px' }}>图</span> : null}
        </button>
        <button
          className="hud-chip hud-btn"
          onClick={() => {
            autoLayout()
            setTimeout(() => {
              try {
                fitView({ padding: 0.16, minZoom: 0.28, maxZoom: 1.05, duration: 280 })
              } catch {
                /* ignore */
              }
            }, 120)
          }}
          title="按流程分层重排节点，减少连线交叉（会覆盖手动摆放的位置）"
        >
          ⤢ 整理布局
        </button>
        <div className="hud-chip dim">虚线是循环回边 · 右键画布新增节点</div>
      </div>

      {bgPanelOpen && <BackgroundPanel onClose={() => setBgPanelOpen(false)} />}
      {constraintPanelOpen && (
        <ConstraintPanel onClose={() => setConstraintPanelOpen(false)} />
      )}

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

      {menu?.kind === 'node' && !linker && (
        <ContextMenu x={menu.x} y={menu.y} onClose={closeMenu} minWidth={216}>
          <div className="group-title" style={{ padding: '4px 9px 6px' }}>
            {nodes.find((n) => n.id === menu.nodeId)?.data.label}
          </div>
          <div
            className="ctx-item"
            onClick={() => {
              openNodePanel(menu.nodeId, 'code')
              setMenu(null)
            }}
          >
            <span className="ico">&lt;/&gt;</span> 编辑代码逻辑
          </div>
          <div
            className="ctx-item"
            onClick={() => {
              openNodePanel(menu.nodeId, 'props')
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
          <div
            className="ctx-item"
            onClick={() => startLinker(menu.nodeId)}
          >
            <span className="ico">➜</span> 连线到其它节点…
          </div>
          {menuNodeUsesLLM && (
            <div
              className="ctx-item"
              onClick={() => {
                setModelNodeId(menu.nodeId)
                setMenu(null)
              }}
            >
              <span className="ico">⚙</span> 配置模型 / API Key
              {!menuNodeIsAgent && <span className="hint">覆盖画布配置</span>}
            </div>
          )}
          <div
            className="ctx-item"
            onClick={() => {
              resetNodeSize(menu.nodeId)
              setMenu(null)
            }}
          >
            <span className="ico">⇲</span> 重置节点尺寸
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

      {/* 右键连线：先选分支（多端口节点），再选目标节点 */}
      {menu?.kind === 'node' && linker && (
        <ContextMenu x={menu.x} y={menu.y} onClose={closeMenu} minWidth={272}>
          <div className="ctx-search">
            <div className="dim small" style={{ padding: '2px 4px' }}>
              {linker.step === 'branch'
                ? `从「${nodes.find((n) => n.id === linker.source)?.data.label}」的哪个出口连出？`
                : `连到「${nodes.find((n) => n.id === linker.source)?.data.label}」的哪个节点？`}
            </div>
          </div>
          {linker.step === 'branch'
            ? ((meta?.nodes.find(
                (x) => x.kind === nodes.find((n) => n.id === linker.source)?.data.kind,
              )?.outputs || ['out']) as string[]).map((h) => (
              <div
                key={h}
                className="ctx-item"
                onClick={() => setLinker({ ...linker, handle: h, step: 'target' })}
              >
                <span className="ico">→</span> {BRANCH_TEXT[h] || h}
              </div>
            ))
            : nodes
                .filter((n) => n.id !== linker.source)
                .map((n) => {
                  const def = meta?.nodes.find((x) => x.kind === n.data.kind)
                  return (
                    <div key={n.id} className="ctx-item" onClick={() => finishLink(n.id)}>
                      <span className="ico" style={{ color: def?.color || '#8b5cf6' }}>
                        {def?.icon || '◆'}
                      </span>
                      <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>
                        {n.data.label}
                      </span>
                      <span className="hint">{n.data.name}</span>
                    </div>
                  )
                })}
          {linker.step === 'target' && nodes.filter((n) => n.id !== linker.source).length === 0 && (
            <div className="ctx-item dim" style={{ cursor: 'default' }}>
              画布上还没有其它节点
            </div>
          )}
          {linker.step === 'target' && (
            <>
              <div className="menu-sep" />
              <div className="ctx-item" onClick={() => setLinker({ ...linker, step: 'branch' })}>
                <span className="ico">←</span> 换个出口
              </div>
            </>
          )}
        </ContextMenu>
      )}

      {modelNodeId && (
        <NodeModelModal nodeId={modelNodeId} onClose={() => setModelNodeId(null)} />
      )}

      {/* 连线右键菜单：改起点 / 改终点 / 重置弯曲 / 删除 */}
      {edgeMenu && (
        <ContextMenu
          x={edgeMenu.x}
          y={edgeMenu.y}
          onClose={() => setEdgeMenu(null)}
          minWidth={230}
        >
          {edgeMenu.mode === 'root' ? (
            <>
              <div className="group-title" style={{ padding: '4px 9px 6px' }}>
                这条连线
              </div>
              <div
                className="ctx-item"
                onClick={() => setEdgeMenu({ ...edgeMenu, mode: 'source' })}
              >
                <span className="ico">⇤</span> 修改起点
              </div>
              <div
                className="ctx-item"
                onClick={() => setEdgeMenu({ ...edgeMenu, mode: 'target' })}
              >
                <span className="ico">⇥</span> 修改终点
              </div>
              <div
                className="ctx-item"
                onClick={() => {
                  updateEdgeData(edgeMenu.edgeId, { controlOffset: { x: 0, y: 0 } })
                  setEdgeMenu(null)
                }}
              >
                <span className="ico">↺</span> 重置弯曲
              </div>
              <div className="menu-sep" />
              <div
                className="ctx-item"
                style={{ color: 'var(--err)' }}
                onClick={() => {
                  removeEdge(edgeMenu.edgeId)
                  setHighlightedNodes([])
                  setEdgeMenu(null)
                }}
              >
                <span className="ico">🗑</span> 删除这条线
              </div>
            </>
          ) : (
            <>
              <div className="ctx-search">
                <div className="dim small" style={{ padding: '2px 4px' }}>
                  选择新的{edgeMenu.mode === 'source' ? '起点' : '终点'}
                </div>
              </div>
              {nodes
                .filter((n) => {
                  const kind = n.data.kind
                  if (edgeMenu.mode === 'source' && kind === 'output') return false
                  if (edgeMenu.mode === 'target' && kind === 'input') return false
                  return true
                })
                .map((n) => {
                  const def = meta?.nodes.find((x) => x.kind === n.data.kind)
                  return (
                    <div
                      key={n.id}
                      className="ctx-item"
                      onClick={() => {
                        updateEdgeEndpoint(
                          edgeMenu.edgeId,
                          edgeMenu.mode as 'source' | 'target',
                          n.id,
                        )
                        setEdgeMenu(null)
                      }}
                    >
                      <span className="ico" style={{ color: def?.color || '#8b5cf6' }}>
                        {def?.icon || '◆'}
                      </span>
                      <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>
                        {n.data.label}
                      </span>
                      <span className="hint">{n.data.name}</span>
                    </div>
                  )
                })}
              <div className="menu-sep" />
              <div className="ctx-item" onClick={() => setEdgeMenu({ ...edgeMenu, mode: 'root' })}>
                <span className="ico">←</span> 返回
              </div>
            </>
          )}
        </ContextMenu>
      )}
    </div>
  )
}
