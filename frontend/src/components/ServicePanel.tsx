import { useState } from 'react'
import { useStore } from '../store'
import { DEFAULT_SERVICE, type ServiceConfig } from '../types'

/**
 * 画布级「服务设置」：把整张画布当成一个后端服务来配置。
 * 入口 / 会话与并发 / 可观测 / 安全，四组；保存后写进 graph.service，
 * 生成项目时会产出 server.py / settings.py / telemetry.py / checkpoint.py。
 */
function mergeService(raw: any): ServiceConfig {
  return {
    entry: { ...DEFAULT_SERVICE.entry, ...(raw?.entry || {}) },
    session: { ...DEFAULT_SERVICE.session, ...(raw?.session || {}) },
    runtime: { ...DEFAULT_SERVICE.runtime, ...(raw?.runtime || {}) },
    observability: { ...DEFAULT_SERVICE.observability, ...(raw?.observability || {}) },
    security: { ...DEFAULT_SERVICE.security, ...(raw?.security || {}) },
  }
}

export default function ServicePanel({ onClose }: { onClose: () => void }) {
  const canvas = useStore((s) => s.canvas)
  const setServiceConfig = useStore((s) => s.setServiceConfig)
  const save = useStore((s) => s.save)
  const toast = useStore((s) => s.toast)
  const [form, setForm] = useState<ServiceConfig>(() =>
    mergeService((canvas?.graph as any)?.service),
  )

  const patch = (group: keyof ServiceConfig, key: string, value: any) =>
    setForm((f) => ({ ...f, [group]: { ...(f[group] as any), [key]: value } }))

  const apply = async () => {
    setServiceConfig(form)
    const ok = await save()
    if (ok) {
      toast('服务设置已保存，生成的项目会带上服务入口', 'ok')
      onClose()
    }
  }

  return (
    <div className="bg-panel service-panel">
      <div className="bg-panel-head">
        <span>服务设置</span>
        <span className="dim small" style={{ marginRight: 8 }}>
          {canvas?.name}
        </span>
        <button className="ghost icon" onClick={onClose} title="关闭">
          ✕
        </button>
      </div>

      <div className="bg-panel-body">
        <div className="bg-section-title">① 服务入口</div>
        <label className="field">
          <span>暴露方式</span>
          <select value={form.entry.mode} onChange={(e) => patch('entry', 'mode', e.target.value)}>
            <option value="both">HTTP + SSE 流式</option>
            <option value="http">仅 HTTP</option>
            <option value="sse">仅 SSE 流式</option>
          </select>
        </label>
        <label className="field">
          <span>接口路径</span>
          <input
            value={form.entry.path}
            placeholder="/chat"
            onChange={(e) => patch('entry', 'path', e.target.value)}
          />
        </label>
        <label className="field">
          <span>鉴权</span>
          <select value={form.entry.auth} onChange={(e) => patch('entry', 'auth', e.target.value)}>
            <option value="none">无（本地）</option>
            <option value="api_key">API Key</option>
            <option value="oidc">OIDC / SSO</option>
          </select>
        </label>
        <label className="field">
          <span>CORS 允许来源</span>
          <input
            value={form.entry.cors}
            placeholder="* 或 https://your.site"
            onChange={(e) => patch('entry', 'cors', e.target.value)}
          />
        </label>

        <div className="bg-section-title" style={{ marginTop: 14 }}>
          ② 会话与并发
        </div>
        <label className="field">
          <span>会话存储</span>
          <select value={form.session.store} onChange={(e) => patch('session', 'store', e.target.value)}>
            <option value="none">无（单次）</option>
            <option value="sqlite">SQLite（本地）</option>
            <option value="postgres">Postgres（生产）</option>
          </select>
        </label>
        <div className="row" style={{ gap: 10 }}>
          <label className="field" style={{ flex: 1 }}>
            <span>最大轮数</span>
            <input
              type="number"
              min={1}
              value={form.session.max_turns}
              onChange={(e) => patch('session', 'max_turns', Number(e.target.value))}
            />
          </label>
          <label className="field" style={{ flex: 1 }}>
            <span>会话 TTL（分钟）</span>
            <input
              type="number"
              min={1}
              value={form.session.ttl_minutes}
              onChange={(e) => patch('session', 'ttl_minutes', Number(e.target.value))}
            />
          </label>
        </div>
        <div className="row" style={{ gap: 10 }}>
          <label className="field" style={{ flex: 1 }}>
            <span>并发上限</span>
            <input
              type="number"
              min={1}
              value={form.runtime.max_concurrency}
              onChange={(e) => patch('runtime', 'max_concurrency', Number(e.target.value))}
            />
          </label>
          <label className="field" style={{ flex: 1 }}>
            <span>排队上限</span>
            <input
              type="number"
              min={1}
              value={form.runtime.queue_limit}
              onChange={(e) => patch('runtime', 'queue_limit', Number(e.target.value))}
            />
          </label>
        </div>
        <label className="field">
          <span>整条 run 超时（秒）</span>
          <input
            type="number"
            min={10}
            value={form.runtime.run_timeout_s}
            onChange={(e) => patch('runtime', 'run_timeout_s', Number(e.target.value))}
          />
        </label>
        <label className="row" style={{ gap: 8 }}>
          <input
            type="checkbox"
            checked={form.runtime.resume}
            onChange={(e) => patch('runtime', 'resume', e.target.checked)}
            style={{ width: 15, height: 15 }}
          />
          <span className="small">开启断点续跑（失败后从最后成功节点恢复）</span>
        </label>

        <div className="bg-section-title" style={{ marginTop: 14 }}>
          ③ 可观测
        </div>
        <div className="row" style={{ gap: 10 }}>
          <label className="field" style={{ flex: 1 }}>
            <span>日志级别</span>
            <select
              value={form.observability.log_level}
              onChange={(e) => patch('observability', 'log_level', e.target.value)}
            >
              <option value="debug">debug</option>
              <option value="info">info</option>
              <option value="warn">warn</option>
              <option value="error">error</option>
            </select>
          </label>
          <label className="field" style={{ flex: 1 }}>
            <span>trace 采样率</span>
            <input
              type="number"
              min={0}
              max={1}
              step={0.1}
              value={form.observability.trace_sample}
              onChange={(e) => patch('observability', 'trace_sample', Number(e.target.value))}
            />
          </label>
        </div>
        <div className="row" style={{ gap: 14, marginTop: 4 }}>
          <label className="row" style={{ gap: 7 }}>
            <input
              type="checkbox"
              checked={form.observability.json_logs}
              onChange={(e) => patch('observability', 'json_logs', e.target.checked)}
              style={{ width: 15, height: 15 }}
            />
            <span className="small">JSON 日志</span>
          </label>
          <label className="row" style={{ gap: 7 }}>
            <input
              type="checkbox"
              checked={form.observability.metrics}
              onChange={(e) => patch('observability', 'metrics', e.target.checked)}
              style={{ width: 15, height: 15 }}
            />
            <span className="small">暴露 /metrics</span>
          </label>
        </div>
        <label className="field">
          <span>预算上限（USD，0 不限）</span>
          <input
            type="number"
            min={0}
            step={0.1}
            value={form.observability.budget_usd}
            onChange={(e) => patch('observability', 'budget_usd', Number(e.target.value))}
          />
        </label>

        <div className="bg-section-title" style={{ marginTop: 14 }}>
          ④ 安全
        </div>
        <label className="field">
          <span>默认执行沙箱</span>
          <select value={form.security.sandbox} onChange={(e) => patch('security', 'sandbox', e.target.value)}>
            <option value="none">不限制</option>
            <option value="restricted">受限（目录白名单 + 资源限制）</option>
            <option value="container">容器隔离</option>
          </select>
        </label>
        <label className="field">
          <span>护栏默认策略</span>
          <select
            value={form.security.guardrail}
            onChange={(e) => patch('security', 'guardrail', e.target.value)}
          >
            <option value="off">关闭</option>
            <option value="log">只记录</option>
            <option value="block">命中即拦截</option>
          </select>
        </label>
        <div className="row" style={{ gap: 14, marginTop: 4 }}>
          <label className="row" style={{ gap: 7 }}>
            <input
              type="checkbox"
              checked={form.security.pii}
              onChange={(e) => patch('security', 'pii', e.target.checked)}
              style={{ width: 15, height: 15 }}
            />
            <span className="small">PII 脱敏</span>
          </label>
          <label className="row" style={{ gap: 7 }}>
            <input
              type="checkbox"
              checked={form.security.audit}
              onChange={(e) => patch('security', 'audit', e.target.checked)}
              style={{ width: 15, height: 15 }}
            />
            <span className="small">审计日志</span>
          </label>
        </div>

        <div className="hint-box" style={{ marginTop: 12 }}>
          这些是「整张画布怎么对外提供服务」的配置，不改变流程图本身；
          保存后会生成 <code className="mono">server.py</code>、<code className="mono">settings.py</code>、
          <code className="mono">telemetry.py</code>、<code className="mono">checkpoint.py</code>。
        </div>

        <div className="row" style={{ marginTop: 12 }}>
          <button className="primary" onClick={apply}>
            保存服务设置
          </button>
          <button onClick={onClose}>取消</button>
        </div>
      </div>
    </div>
  )
}
