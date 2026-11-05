import { useEffect, useMemo, useRef, useState } from 'react'
import { useStore } from '../store'
import type { RunEvent } from '../types'

function timeOf(i: number): string {
  const d = new Date()
  return d.toLocaleTimeString('zh-CN', { hour12: false })
}

export default function RunPanel() {
  const open = useStore((s) => s.runPanelOpen)
  const setOpen = useStore((s) => s.setRunPanelOpen)
  const running = useStore((s) => s.running)
  const events = useStore((s) => s.runEvents)
  const output = useStore((s) => s.runOutput)
  const error = useStore((s) => s.runError)
  const input = useStore((s) => s.runInput)
  const setInput = useStore((s) => s.setRunInput)
  const run = useStore((s) => s.run)
  const stopRun = useStore((s) => s.stopRun)
  const canvas = useStore((s) => s.canvas)

  const [tab, setTab] = useState<'events' | 'output'>('events')
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (scrollRef.current && tab === 'events') {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [events, tab])

  useEffect(() => {
    if (output) setTab('output')
  }, [output])

  const rows = useMemo(() => events.filter((e) => e.event !== 'token'), [events])

  const renderEvent = (e: RunEvent, idx: number) => {
    const name = e.name || e.node || ''
    switch (e.event) {
      case 'node_start':
        return (
          <div key={idx} className="evt node-start">
            <span className="time">{timeOf(idx)}</span>
            <span className="tag">执行</span>
            <span className="msg">
              {e.label ? `${e.label}（${name}）` : name}
              {e.visit && e.visit > 1 ? ` · 第 ${e.visit} 次` : ''}
            </span>
          </div>
        )
      case 'node_end':
        return (
          <div key={idx} className="evt node-end">
            <span className="time">{timeOf(idx)}</span>
            <span className="tag">完成</span>
            <span className="msg">
              {name} · {e.duration_ms}ms
              {typeof e.output === 'string' && e.output
                ? ` → ${String(e.output).slice(0, 120).replace(/\n/g, ' ')}`
                : ''}
            </span>
          </div>
        )
      case 'error':
        return (
          <div key={idx} className="evt error">
            <span className="time">{timeOf(idx)}</span>
            <span className="tag">错误</span>
            <span className="msg">{e.message}</span>
          </div>
        )
      case 'log':
        return (
          <div key={idx} className="evt log">
            <span className="time">{timeOf(idx)}</span>
            <span className="tag">{e.level === 'warn' ? '警告' : '日志'}</span>
            <span className="msg">{e.message}</span>
          </div>
        )
      case 'route':
        return (
          <div key={idx} className="evt route">
            <span className="time">{timeOf(idx)}</span>
            <span className="tag">分支</span>
            <span className="msg">走 {e.branch} → {e.target}</span>
          </div>
        )
      case 'custom':
        return (
          <div key={idx} className="evt log">
            <span className="time">{timeOf(idx)}</span>
            <span className="tag">{e.type}</span>
            <span className="msg">{JSON.stringify(e.payload).slice(0, 220)}</span>
          </div>
        )
      case 'tool_call':
        return (
          <div key={idx} className="evt log">
            <span className="time">{timeOf(idx)}</span>
            <span className="tag">工具</span>
            <span className="msg">
              {e.tool}({JSON.stringify(e.args).slice(0, 120)}) → {String(e.result).slice(0, 160)}
            </span>
          </div>
        )
      case 'prepared':
        return (
          <div key={idx} className="evt log">
            <span className="time">{timeOf(idx)}</span>
            <span className="tag">准备</span>
            <span className="msg">
              {e.framework} · {e.model || '未配置模型'} · {e.has_api_key ? '已配置 key' : '未配置 key'}
            </span>
          </div>
        )
      case 'run_end':
        return (
          <div key={idx} className={`evt ${e.status === 'ok' ? 'node-end' : 'error'}`}>
            <span className="time">{timeOf(idx)}</span>
            <span className="tag">结束</span>
            <span className="msg">
              {e.status === 'ok' ? '运行完成' : `运行失败：${e.error || e.message || ''}`}
              {e.duration_ms ? ` · ${e.duration_ms}ms` : ''}
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
