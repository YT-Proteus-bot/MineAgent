import { useEffect, useMemo, useRef, useState } from 'react'
import { useStore } from '../store'
import type { RunEvent } from '../types'

/**
 * 日志前面的时间用事件自身的产生时间（后端发过来时带 at），
 * 不能用 new Date()——那样每渲染一次都会变成"现在"。
 */
function timeOf(e: RunEvent | undefined): string {
  const iso = (e as any)?.at as string | undefined
  const d = iso ? new Date(iso) : null
  if (!d || Number.isNaN(d.getTime())) return '--:--:--'
  return d.toLocaleTimeString('zh-CN', { hour12: false })
}

function outText(v: any): string {
  if (v === null || v === undefined) return ''
  if (typeof v === 'string') return v
  try {
    return JSON.stringify(v, null, 2)
  } catch {
    return String(v)
  }
}

export default function RunPanel() {
  const open = useStore((s) => s.runPanelOpen)
  const setOpen = useStore((s) => s.setRunPanelOpen)
  const running = useStore((s) => s.running)
  const events = useStore((s) => s.runEvents)
  const output = useStore((s) => s.runOutput)
  const stream = useStore((s) => s.runStream)
  const error = useStore((s) => s.runError)
  const input = useStore((s) => s.runInput)
  const setInput = useStore((s) => s.setRunInput)
  const run = useStore((s) => s.run)
  const stopRun = useStore((s) => s.stopRun)
  const canvas = useStore((s) => s.canvas)

  const [tab, setTab] = useState<'events' | 'output'>('events')
  const [elapsed, setElapsed] = useState(0)
  const scrollRef = useRef<HTMLDivElement>(null)
  const startedRef = useRef(0)

  useEffect(() => {
    if (!running) {
      startedRef.current = 0
      setElapsed(0)
      return
    }
    if (!startedRef.current) startedRef.current = Date.now()
    const timer = setInterval(() => {
      setElapsed((Date.now() - startedRef.current) / 1000)
    }, 200)
    return () => clearInterval(timer)
  }, [running])

  useEffect(() => {
    if (scrollRef.current && tab === 'events') {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [events, stream, tab])

  useEffect(() => {
    if (output) setTab('output')
  }, [output])

  const rows = useMemo(() => events.filter((e) => e.event !== 'token'), [events])
  const booting = running && !rows.some((e) => e.event === 'node_start')

  const renderEvent = (e: RunEvent, idx: number) => {
    const name = e.name || e.node || ''
    switch (e.event) {
      case 'node_start':
        return (
          <div key={idx} className="evt node-start">
            <span className="time">{timeOf(e)}</span>
            <span className="tag">执行</span>
            <span className="msg">
              {e.label ? `${e.label}（${name}）` : name}
              {e.visit && e.visit > 1 ? ` · 第 ${e.visit} 次` : ''}
            </span>
          </div>
        )
      case 'node_end': {
        const text = outText(e.output).trim()
        return (
          <div key={idx} className="evt node-end">
            <div className="evt-line">
              <span className="time">{timeOf(e)}</span>
              <span className="tag">完成</span>
              <span className="msg">
                {name}
                {typeof e.duration_ms === 'number' ? ` · ${(e.duration_ms / 1000).toFixed(2)}s` : ''}
              </span>
            </div>
            {text && <pre className="evt-out">{text.slice(0, 3000)}</pre>}
          </div>
        )
      }
      case 'error':
        return (
          <div key={idx} className="evt error">
            <span className="time">{timeOf(e)}</span>
            <span className="tag">错误</span>
            <span className="msg">{e.message}</span>
          </div>
        )
      case 'log':
        return (
          <div key={idx} className="evt log">
            <span className="time">{timeOf(e)}</span>
            <span className="tag">{e.level === 'warn' ? '警告' : '日志'}</span>
            <span className="msg">{e.message}</span>
          </div>
        )
      case 'route':
        return (
          <div key={idx} className="evt route">
            <span className="time">{timeOf(e)}</span>
            <span className="tag">分支</span>
            <span className="msg">
              走 {e.branch} → {e.target}
            </span>
          </div>
        )
      case 'custom':
        return (
          <div key={idx} className="evt log">
            <span className="time">{timeOf(e)}</span>
            <span className="tag">{e.type}</span>
            <span className="msg">{JSON.stringify(e.payload).slice(0, 220)}</span>
          </div>
        )
      case 'tool_call':
        return (
          <div key={idx} className="evt log">
            <span className="time">{timeOf(e)}</span>
            <span className="tag">工具</span>
            <span className="msg">
              {e.tool}({JSON.stringify(e.args).slice(0, 120)}) → {String(e.result).slice(0, 160)}
            </span>
          </div>
        )
      case 'prepared':
        return (
          <div key={idx} className="evt log">
            <span className="time">{timeOf(e)}</span>
            <span className="tag">准备</span>
            <span className="msg">
              {e.framework} · {e.model || '未配置模型'} · {e.has_api_key ? '已配置 key' : '未配置 key'}
              {e.run_mode === 'native' ? (
                <b style={{ color: 'var(--ok)' }}> · 真实运行 {e.entry || 'agent.py'}</b>
              ) : (
                <span style={{ color: 'var(--warn)' }}> · 零依赖预览（装框架依赖后会跑 agent.py）</span>
              )}
            </span>
          </div>
        )
      case 'run_end':
        return (
          <div key={idx} className={`evt ${e.status === 'ok' ? 'node-end' : 'error'}`}>
            <span className="time">{timeOf(e)}</span>
            <span className="tag">结束</span>
            <span className="msg">
              {e.status === 'ok' ? '运行完成' : `运行失败：${e.error || e.message || ''}`}
              {e.duration_ms ? ` · ${(e.duration_ms / 1000).toFixed(2)}s` : ''}
            </span>
          </div>
        )
      default:
        return null
    }
  }

  return (
    <section className={`run-panel${open ? '' : ' collapsed'}`}>
      <div className="run-head">
        <button className="ghost sm" onClick={() => setOpen(!open)}>
          {open ? '▾' : '▴'} 运行面板
        </button>
        <span className="dim small">{canvas?.name}</span>
        {running && (
          <span className="row small" style={{ gap: 6 }}>
            <span className="spin" /> 正在执行
            <span className="dim mono">{elapsed.toFixed(1)}s</span>
          </span>
        )}
        <div style={{ flex: 1 }} />
        {running ? (
          <button className="sm danger" onClick={stopRun}>
            停止
          </button>
        ) : (
          <button className="sm primary" onClick={() => run(input)} disabled={!canvas}>
            ▶ 运行
          </button>
        )}
      </div>

      {open && (
        <div className="run-body">
          <div className="run-left">
            <div className="dim small">任务输入（会传给 input 节点）</div>
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="例如：调研 2025 年国产 Agent 编排平台的差异，输出一份对比报告…"
              onKeyDown={(e) => {
                if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') run(input)
              }}
            />
            <div className="row">
              <button className="primary sm" onClick={() => run(input)} disabled={running}>
                {running ? '运行中…' : '▶ 开始运行'}
              </button>
              <span className="dim small">Ctrl+Enter</span>
            </div>
            {error && (
              <div className="hint-box" style={{ color: 'var(--err)', borderColor: '#4d2028' }}>
                {error}
              </div>
            )}
          </div>

          <div className="run-right">
            <div className="run-tabs">
              <div className={`tab${tab === 'events' ? ' active' : ''}`} onClick={() => setTab('events')}>
                执行过程（{rows.length}）
              </div>
              <div className={`tab${tab === 'output' ? ' active' : ''}`} onClick={() => setTab('output')}>
                最终输出
              </div>
            </div>

            {tab === 'events' ? (
              <div className="run-scroll" ref={scrollRef}>
                {(running || stream) && (
                  <div className="run-live">
                    <div className="run-live-head">
                      <span className={running ? 'spin' : 'dot-ok'} />
                      {booting
                        ? '正在启动执行进程（首次启动需加载框架依赖，约 3–5 秒）'
                        : running
                          ? `正在执行：${stream?.name || stream?.node || '等待节点输出…'}`
                          : `上一个节点：${stream?.name || stream?.node || ''}`}
                    </div>
                    <pre className="run-live-text">
                      {stream?.text || (booting ? '准备中…' : '…')}
                    </pre>
                  </div>
                )}
                {rows.length === 0 && <div className="dim">还没有运行记录</div>}
                {rows.map(renderEvent)}
              </div>
            ) : (
              <div className="run-scroll">
                <div className="run-output">{output || <span className="dim">运行结束后在这里显示结果</span>}</div>
              </div>
            )}
          </div>
        </div>
      )}
    </section>
  )
}
