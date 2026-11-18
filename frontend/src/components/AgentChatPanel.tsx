import { useEffect, useRef, useState } from 'react'
import { assistantChat, api, type ChatMsg } from '../api'
import { useStore } from '../store'

const QUICK = [
  'ReAct 和 Plan-and-Execute 我该选哪个？',
  '为什么我的画布运行被约束拦下了？',
  'RAG 那一段节点该怎么串？',
  '节点代码里 ctx 有哪些能力？',
]

type ChatBrief = {
  id: string
  title: string
  message_count: number
  updated_at: string
}

/** 助手在回复里用 ```canvas 块给出整张画布草稿、用 ```ops 块给出增量操作 */
type CanvasDraft = { nodes: any[]; edges?: any[] }

function parseBlocks(text: string): {
  draft: CanvasDraft | null
  ops: any[] | null
  body: string
} {
  let body = text
  let draft: CanvasDraft | null = null
  let ops: any[] | null = null

  const cm = body.match(/```canvas\s*\n([\s\S]*?)```/)
  if (cm) {
    try {
      const parsed = JSON.parse(cm[1])
      if (Array.isArray(parsed?.nodes) && parsed.nodes.length > 0) {
        draft = parsed
        body = body.replace(cm[0], '').trim()
      }
    } catch {
      /* 解析失败就当普通文本 */
    }
  }

  const om = body.match(/```ops\s*\n([\s\S]*?)```/)
  if (om) {
    try {
      const parsed = JSON.parse(om[1])
      if (Array.isArray(parsed) && parsed.length > 0) {
        ops = parsed
        body = body.replace(om[0], '').trim()
      }
    } catch {
      /* 同上 */
    }
  }

  return { draft, ops, body }
}

/** 增量操作的简短说明，做成卡片上的一行摘要 */
function describeOps(ops: any[]): string {
  const labels: Record<string, string> = {
    add_node: '新增',
    remove_node: '删除',
    update_node: '改参数',
    set_code: '改代码',
    connect: '连线',
    disconnect: '断线',
    move_node: '移位置',
    relayout: '重排',
  }
  const counts: Record<string, number> = {}
  for (const op of ops) {
    const key = String(op?.op || '')
    counts[key] = (counts[key] || 0) + 1
  }
  return Object.entries(counts)
    .map(([key, n]) => `${labels[key] || key} ${n}`)
    .join(' · ')
}

/** 常驻 AI 助手：用「用户中心」配置的 key，回答使用中遇到的框架 / 编排问题。 */
export default function AgentChatPanel() {
  const canvas = useStore((s) => s.canvas)
  const nodes = useStore((s) => s.nodes)
  const edges = useStore((s) => s.edges)
  const report = useStore((s) => s.constraintReport)
  const runError = useStore((s) => s.runError)
  const runEvents = useStore((s) => s.runEvents)
  const selectedId = useStore((s) => s.selectedNodeId)
  const toast = useStore((s) => s.toast)
  const loadCanvas = useStore((s) => s.loadCanvas)

  const [messages, setMessages] = useState<ChatMsg[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [withContext, setWithContext] = useState(true)
  const [ready, setReady] = useState<boolean | null>(null)
  const [hint, setHint] = useState('')
  const [chatId, setChatId] = useState<string | null>(null)
  const [chats, setChats] = useState<ChatBrief[]>([])
  const [historyOpen, setHistoryOpen] = useState(false)
  const [applying, setApplying] = useState(false)
  // Agent 状态：正在跑的工具、待用户确认的动作、早前对话的摘要
  const [toolRunning, setToolRunning] = useState('')
  const [pending, setPending] = useState<{ tool: string; payload: any } | null>(null)
  const [summary, setSummary] = useState('')
  const listRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)
  const accRef = useRef('')

  useEffect(() => {
    api
      .assistantStatus()
      .then((s) => {
        setReady(s.ready)
        setHint(s.hint)
      })
      .catch(() => setReady(false))
  }, [])

  const canvasId = canvas?.id || ''

  const refreshChats = () => {
    if (!canvasId) {
      setChats([])
      return
    }
    api
      .listChats(canvasId)
      .then(setChats)
      .catch(() => setChats([]))
  }

  // 每张画布的对话各自独立：切画布时先清空，再恢复这张画布最近的一次对话，
  // 避免把上一张画布的上下文带过来。
  useEffect(() => {
    // 切画布时如果还在等回复，先把上一次请求断掉
    abortRef.current?.abort()
    abortRef.current = null
    setBusy(false)
    setMessages([])
    setChatId(null)
    setHistoryOpen(false)
    accRef.current = ''
    setSummary('')
    setPending(null)
    setToolRunning('')
    if (!canvasId) {
      setChats([])
      return
    }
    let alive = true
    api
      .listChats(canvasId)
      .then(async (list) => {
        if (!alive) return
        setChats(list)
        if (!list.length) return
        const d = await api.getChat(list[0].id)
        if (!alive) return
        setChatId(d.id)
        setMessages(d.messages || [])
        setSummary((d as any).summary || '')
      })
      .catch(() => {
        if (alive) setChats([])
      })
    return () => {
      alive = false
    }
  }, [canvasId])

  useEffect(() => {
    if (listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight
  }, [messages])

  const buildContext = () => {
    if (!withContext) return {}
    const sel = nodes.find((n) => n.id === selectedId)
    // 运行面板里的执行过程：带 id/时间/错误，让助手能定位到具体节点
    const runLog = runEvents
      .filter((e) =>
        ['node_start', 'node_end', 'error', 'final', 'run_end', 'prepared'].includes(
          String(e.event),
        ),
      )
      .slice(-80)
      .map((e) => ({
        event: String(e.event),
        node: e.name || e.node || '',
        at: e.at || '',
        duration_ms: e.duration_ms,
        level: e.level,
        message: e.message ? String(e.message).slice(0, 300) : undefined,
        output:
          typeof e.output === 'string'
            ? e.output.slice(0, 300)
            : e.output !== undefined
              ? JSON.stringify(e.output).slice(0, 300)
              : undefined,
      }))
    return {
      canvas: canvas
        ? {
            name: canvas.name,
            framework: canvas.framework,
            node_count: nodes.length,
            edge_count: edges.length,
          }
        : null,
      nodes: nodes.slice(0, 40).map((n) => ({
        id: n.id,
        label: n.data.label,
        kind: n.data.kind,
        name: n.data.name,
      })),
      edges: edges.slice(0, 60).map((e) => ({
        source: e.source,
        target: e.target,
        branch: e.sourceHandle || '',
      })),
      violations: (report?.violations || []).slice(0, 6).map((v) => ({
        level: v.level,
        title: v.title,
        message: v.message,
      })),
      last_run: runError || '',
      run_log: runLog,
      selected: sel
        ? { id: sel.id, label: sel.data.label, kind: sel.data.kind, name: sel.data.name }
        : null,
    }
  }

  const persist = async (msgs: ChatMsg[]) => {
    if (!msgs.length) return
    try {
      const res = await api.saveChat({
        messages: msgs,
        chat_id: chatId || undefined,
        canvas_id: canvas?.id,
        summary,
      })
      if (!chatId && res.id) setChatId(res.id)
      refreshChats()
    } catch {
      /* 保存失败不影响对话 */
    }
  }

  const send = async (text: string) => {
    const content = text.trim()
    if (!content || busy) return
    setInput('')
    setPending(null)
    const next: ChatMsg[] = [...messages, { role: 'user', content }]
    const assistantIndex = next.length
    setMessages([...next, { role: 'assistant', content: '' }])
    setBusy(true)

    const controller = new AbortController()
    abortRef.current = controller
    accRef.current = ''

    await assistantChat(
      {
        messages: next,
        context: buildContext(),
        canvasId: canvas?.id || '',
        summary,
        onToken: (token) => {
          accRef.current += token
          setMessages((prev) => {
            const copy = [...prev]
            const last = copy[assistantIndex]
            if (last) copy[assistantIndex] = { ...last, content: last.content + token }
            return copy
          })
        },
        onError: (msg) => {
          setMessages((prev) => {
            const copy = [...prev]
            copy[assistantIndex] = { role: 'assistant', content: `⚠ ${msg}` }
            return copy
          })
          setBusy(false)
        },
        onDone: () => setBusy(false),
        onEvent: (evt) => {
          if (evt.event === 'tool_start') {
            setToolRunning(evt.tool || '')
          } else if (evt.event === 'tool_end') {
            setToolRunning('')
          } else if (evt.event === 'pending') {
            setPending({ tool: evt.tool || '', payload: evt.payload || {} })
          }
        },
      },
      controller.signal,
    )
    setBusy(false)
    setToolRunning('')
    abortRef.current = null

    const finalMsgs: ChatMsg[] = [...next]
    if (accRef.current.trim()) finalMsgs.push({ role: 'assistant', content: accRef.current })
    persist(finalMsgs)

    // 对话变长时压缩早期内容，后面的轮次只带摘要 + 最近几条
    if (finalMsgs.length > 30) {
      try {
        const res = await api.compressChat(finalMsgs, canvas?.id || '')
        if (res.summary) {
          setSummary(res.summary)
          setMessages(finalMsgs.slice(-10))
        }
      } catch {
        /* 压缩失败不影响对话 */
      }
    }
  }

  const stop = () => {
    abortRef.current?.abort()
    abortRef.current = null
    setBusy(false)
    // 中断时也把已有的部分存下来
    const partial: ChatMsg[] = [...messages]
    if (accRef.current.trim()) partial.push({ role: 'assistant', content: accRef.current })
    persist(partial)
  }

  /** 应用增量操作（增删节点 / 改参数与代码 / 连线 / 挪位置） */
  const applyOps = async (ops: any[]) => {
    if (!canvas) {
      toast('先打开一张画布再应用', 'err')
      return
    }
    setApplying(true)
    try {
      const res = await api.applyOps(canvas.id, ops)
      await loadCanvas(canvas.id)
      if (res.errors?.length) {
        toast(`应用了 ${res.applied} 项，${res.errors.length} 项失败：${res.errors[0]}`, 'err')
      } else {
        toast(`已应用 ${res.applied} 项修改`, 'ok')
      }
    } catch (e: any) {
      toast(`应用失败：${e.message || e}`, 'err')
    } finally {
      setApplying(false)
    }
  }

  /** 应用 Agent 提出的待确认动作 */
  const applyPending = async (p: { tool: string; payload: any }) => {
    if (!canvas) return
    if (p.tool === 'apply_ops') {
      await applyOps(p.payload.operations || [])
      setPending(null)
      return
    }
    if (p.tool === 'apply_canvas') {
      await applyDraft({
        nodes: p.payload.nodes || [],
        edges: p.payload.edges || [],
      })
      setPending(null)
      return
    }
    if (p.tool === 'run_canvas') {
      toast(`运行输入：${String(p.payload.input || '').slice(0, 60)}。点顶部「▶ 运行」即可`, 'info')
      setPending(null)
    }
  }

  const pendingInfo = (p: { tool: string; payload: any }) => {
    if (p.tool === 'apply_ops') {
      const ops = p.payload.operations || []
      return { title: '助手要修改画布（增量）', detail: describeOps(ops), label: '应用这些修改' }
    }
    if (p.tool === 'apply_canvas') {
      const nodes = p.payload.nodes || []
      return {
        title: '助手生成新画布（整张替换）',
        detail: `${nodes.length} 个节点 · ${(p.payload.edges || []).length} 条连线`,
        label: '应用到当前画布',
      }
    }
    return {
      title: '助手要运行画布',
      detail: String(p.payload.input || ''),
      label: '知道了',
    }
  }

  /** 把助手生成的画布替换到当前画布（替换前确认，避免误丢内容） */
  const applyDraft = async (draft: CanvasDraft) => {
    if (!canvas) {
      toast('先打开一张画布再应用', 'err')
      return
    }
    const currentCount = nodes.length
    if (currentCount > 0) {
      const ok = window.confirm(
        `这会用助手生成的 ${draft.nodes.length} 个节点替换当前画布的 ${currentCount} 个节点，\n` +
          '当前画布上的节点、连线和手写代码都会丢失。确定替换吗？',
      )
      if (!ok) return
    }
    setApplying(true)
    try {
      const res = await api.applyDraft(canvas.id, draft)
      await loadCanvas(canvas.id)
      const errs = res.constraints?.errors?.length || 0
      const warns = res.constraints?.warnings?.length || 0
      if (errs) {
        toast(`已应用，但有 ${errs} 条约束未通过，点顶部「⚠ 约束」查看`, 'err')
      } else if (warns) {
        toast(`已应用，有 ${warns} 条提醒`, 'info')
      } else {
        toast('已应用到当前画布', 'ok')
      }
    } catch (e: any) {
      toast(`应用失败：${e.message || e}`, 'err')
    } finally {
      setApplying(false)
    }
  }

  const startNewChat = () => {
    setMessages([])
    setChatId(null)
    setHistoryOpen(false)
    accRef.current = ''
    setSummary('')
    setPending(null)
    setToolRunning('')
  }

  const openChat = async (id: string) => {
    try {
      const d = await api.getChat(id)
      setChatId(d.id)
      setMessages(d.messages || [])
      setHistoryOpen(false)
    } catch (e: any) {
      toast(`打开失败：${e.message || e}`, 'err')
    }
  }

  const removeChat = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation()
    try {
      await api.deleteChat(id)
      if (id === chatId) startNewChat()
      refreshChats()
    } catch (err: any) {
      toast(`删除失败：${err.message || err}`, 'err')
    }
  }

  const fmtTime = (iso: string) => {
    if (!iso) return ''
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return iso.slice(5, 16)
    return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:${String(
      d.getMinutes(),
    ).padStart(2, '0')}`
  }

  return (
    <div className="chat-panel">
      <div className="chat-head">
        <button className="ghost sm" onClick={startNewChat} disabled={busy} title="开一段新对话">
          ＋ 新对话
        </button>
        <div className="chat-history-wrap">
          <button
            className={`ghost sm${historyOpen ? ' active' : ''}`}
            onClick={() => {
              setHistoryOpen((v) => !v)
              refreshChats()
            }}
            title="查看历史对话"
          >
            🕘 历史{chats.length ? ` ${chats.length}` : ''}
          </button>
          {historyOpen && (
            <div className="chat-history">
              {chats.length === 0 && <div className="dim small" style={{ padding: 10 }}>还没有历史对话</div>}
              {chats.map((c) => (
                <div
                  key={c.id}
                  className={`chat-history-item${c.id === chatId ? ' active' : ''}`}
                  onClick={() => openChat(c.id)}
                >
                  <div className="ch-title">{c.title || '新对话'}</div>
                  <div className="ch-meta">
                    {fmtTime(c.updated_at)} · {c.message_count} 条
                  </div>
                  <span className="ch-del" title="删除这段对话" onClick={(e) => removeChat(c.id, e)}>
                    ×
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
        <div style={{ flex: 1 }} />
        <label className="row small" style={{ gap: 5 }} title="把当前画布、约束问题和最近报错一起发给助手">
          <input
            type="checkbox"
            checked={withContext}
            onChange={(e) => setWithContext(e.target.checked)}
            style={{ width: 13, height: 13 }}
          />
          带上画布上下文
        </label>
      </div>

      <div className="chat-list" ref={listRef}>
        {messages.length === 0 && (
          <div className="chat-empty">
            <div style={{ fontSize: 22, marginBottom: 6 }}>✦</div>
            <div>遇到框架或编排上的问题，直接问。</div>
            <div className="dim small" style={{ marginTop: 6 }}>
              用的是「用户中心」里配置的模型 key
              {ready === false && hint ? ` · ${hint}` : ''}
            </div>
            <div className="chat-quick">
              {QUICK.map((q) => (
                <button key={q} className="sm" onClick={() => send(q)} disabled={busy}>
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((m, i) => {
          const parsed = m.role === 'assistant'
            ? parseBlocks(m.content || '')
            : { draft: null, ops: null, body: m.content }
          const draft = parsed.draft as CanvasDraft | null
          const ops = parsed.ops as any[] | null
          return (
            <div key={i} className={`chat-msg ${m.role}`}>
              {parsed.body || (busy && i === messages.length - 1 ? '思考中…' : '')}
              {draft && (
                <div className="chat-canvas-card">
                  <div className="chat-canvas-meta">
                    <b>助手生成的画布（整张替换）</b>
                    <span className="dim small">
                      {draft.nodes.length} 个节点 · {draft.edges?.length || 0} 条连线
                    </span>
                  </div>
                  <button
                    className="sm primary"
                    disabled={applying || !canvas}
                    onClick={() => applyDraft(draft)}
                  >
                    {applying ? '应用中…' : '应用到当前画布'}
                  </button>
                </div>
              )}
              {ops && (
                <div className="chat-canvas-card">
                  <div className="chat-canvas-meta">
                    <b>助手要修改画布（增量）</b>
                    <span className="dim small">{describeOps(ops)}</span>
                  </div>
                  <button
                    className="sm primary"
                    disabled={applying || !canvas}
                    onClick={() => applyOps(ops)}
                  >
                    {applying ? '应用中…' : '应用这些修改'}
                  </button>
                </div>
              )}
            </div>
          )
        })}

        {toolRunning && (
          <div className="chat-tool-running">
            <span className="spin">◌</span> 正在调用 {toolRunning}…
          </div>
        )}

        {pending && (
          <div className="chat-canvas-card">
            <div className="chat-canvas-meta">
              <b>{pendingInfo(pending).title}</b>
              <span className="dim small">{pendingInfo(pending).detail}</span>
            </div>
            <button
              className="sm primary"
              disabled={applying}
              onClick={() => applyPending(pending)}
            >
              {applying ? '应用中…' : pendingInfo(pending).label}
            </button>
            <button className="sm" onClick={() => setPending(null)}>
              忽略
            </button>
          </div>
        )}
      </div>

      <div className="chat-input">
        <textarea
          value={input}
          placeholder="描述你遇到的问题，或贴一段报错…"
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              send(input)
            }
          }}
        />
        <div className="row">
          <span className="dim small">Enter 发送 · Shift+Enter 换行</span>
          <div style={{ flex: 1 }} />
          {busy ? (
            <button className="sm danger" onClick={stop}>
              停止
            </button>
          ) : (
            <button className="sm primary" onClick={() => send(input)} disabled={!input.trim()}>
              发送
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
