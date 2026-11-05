import { useEffect, useRef, useState } from 'react'
import { assistantChat, api, type ChatMsg } from '../api'
import { useStore } from '../store'

const QUICK = [
  'ReAct 和 Plan-and-Execute 我该选哪个？',
  '为什么我的画布运行被约束拦下了？',
  'RAG 那一段节点该怎么串？',
  '节点代码里 ctx 有哪些能力？',
]

/** 常驻 AI 助手：用「用户中心」配置的 key，回答使用中遇到的框架 / 编排问题。 */
export default function AgentChatPanel() {
  const canvas = useStore((s) => s.canvas)
  const nodes = useStore((s) => s.nodes)
  const edges = useStore((s) => s.edges)
  const report = useStore((s) => s.constraintReport)
  const runError = useStore((s) => s.runError)
  const selectedId = useStore((s) => s.selectedNodeId)

  const [messages, setMessages] = useState<ChatMsg[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [withContext, setWithContext] = useState(true)
  const [ready, setReady] = useState<boolean | null>(null)
  const [hint, setHint] = useState('')
  const listRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    api
      .assistantStatus()
      .then((s) => {
        setReady(s.ready)
        setHint(s.hint)
      })
      .catch(() => setReady(false))
  }, [])

  useEffect(() => {
    if (listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight
  }, [messages])

  const buildContext = () => {
    if (!withContext) return {}
    const sel = nodes.find((n) => n.id === selectedId)
    return {
      canvas: canvas
        ? {
            name: canvas.name,
            framework: canvas.framework,
            node_count: nodes.length,
            edge_count: edges.length,
          }
        : null,
      nodes: nodes.slice(0, 30).map((n) => ({
        label: n.data.label,
        kind: n.data.kind,
        name: n.data.name,
      })),
      violations: (report?.violations || []).slice(0, 6).map((v) => ({
        level: v.level,
        title: v.title,
        message: v.message,
      })),
      last_run: runError || '',
      selected: sel ? { label: sel.data.label, kind: sel.data.kind, name: sel.data.name } : null,
    }
  }

  const send = async (text: string) => {
    const content = text.trim()
    if (!content || busy) return
    setInput('')
    const next: ChatMsg[] = [...messages, { role: 'user', content }]
    setMessages(next)
    setBusy(true)

    const assistantIndex = next.length
    setMessages([...next, { role: 'assistant', content: '' }])
    const controller = new AbortController()
    abortRef.current = controller

    await assistantChat(
      next,
      buildContext(),
      (token) => {
        setMessages((prev) => {
          const copy = [...prev]
          const last = copy[assistantIndex]
          if (last) copy[assistantIndex] = { ...last, content: last.content + token }
          return copy
        })
      },
      (msg) => {
        setMessages((prev) => {
          const copy = [...prev]
          copy[assistantIndex] = {
            role: 'assistant',
            content: `⚠ ${msg}`,
          }
          return copy
        })
        setBusy(false)
      },
      () => setBusy(false),
      controller.signal,
    )
    setBusy(false)
    abortRef.current = null
  }

  const stop = () => {
    abortRef.current?.abort()
    abortRef.current = null
    setBusy(false)
  }

  return (
    <div className="chat-panel">
      <div className="chat-head">
        <button
          className="ghost sm"
          onClick={() => setMessages([])}
          disabled={busy || messages.length === 0}
          title="清空当前对话"
        >
          ＋ 新对话
        </button>
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

        {messages.map((m, i) => (
          <div key={i} className={`chat-msg ${m.role}`}>
            {m.content || (busy && i === messages.length - 1 ? '思考中…' : '')}
          </div>
        ))}
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
