import { useEffect, useState } from 'react'
import { useStore } from '../store'
import { api } from '../api'
import { type ServiceConfig } from '../types'
import { datasetsText, mergeService, parseDatasets } from '../serviceConfig'

/**
 * 画布级「服务设置」：把整张画布当成一个后端服务来配置。
 * 入口 / 会话与并发 / 可观测 / 安全，四组；保存后写进 graph.service，
 * 生成项目时会产出 server.py / settings.py / telemetry.py / checkpoint.py。
 */
function evalsetsText(list: { logical: string; remote: string }[]): string {
  return (list || []).map((e) => `${e.logical} = ${e.remote}`).join('\n')
}

export default function ServicePanel({ onClose }: { onClose: () => void }) {
  const canvas = useStore((s) => s.canvas)
  const setServiceConfig = useStore((s) => s.setServiceConfig)
  const save = useStore((s) => s.save)
  const toast = useStore((s) => s.toast)
  const setSyncConflict = useStore((s) => s.setSyncConflict)
  const refreshCanvases = useStore((s) => s.refreshCanvases)
  const loadCanvas = useStore((s) => s.loadCanvas)
  const [form, setForm] = useState<ServiceConfig>(() =>
    mergeService((canvas?.graph as any)?.service),
  )
  const [updating, setUpdating] = useState(false)
  const [syncDetail, setSyncDetail] = useState<{
    remote_rev?: number
    local_rev?: number
    remote_updated_at?: string
    remote_changed?: boolean
    local_changed?: boolean
  } | null>(null)

  useEffect(() => {
    if (!canvas?.id) return
    let alive = true
    api
      .communitySyncStatus(canvas.id)
      .then((res) => {
        if (alive && res.linked) setSyncDetail(res)
      })
      .catch(() => {
        /* 没连 GitHub 或模板不存在时忽略，用列表里的快照兜底 */
      })
    return () => {
      alive = false
    }
  }, [canvas?.id])

  // ---- 远端同步信息（优先用 sync-status 的实时值）----
  const remoteSlug = canvas?.remote_slug || ''
  const remoteName = canvas?.remote_name || ''
  const libLabel = canvas?.remote_lib_label || '公共模板库'
  const localRev = syncDetail?.local_rev ?? canvas?.remote_rev ?? 0
  const remoteRev = syncDetail?.remote_rev ?? canvas?.remote_rev ?? 0
  const remoteChanged = syncDetail?.remote_changed ?? !!canvas?.remote_changed
  const localChanged = syncDetail?.local_changed ?? !!canvas?.local_changed
  const remoteUpdatedAt = syncDetail?.remote_updated_at || ''

  const syncState = !remoteSlug
    ? { text: '未关联远端', cls: 'dim' }
    : remoteChanged
      ? { text: '远端有更新', cls: 'warn-text' }
      : localChanged
        ? { text: '本地已改动，待推送', cls: 'dim' }
        : { text: '已同步', cls: 'ok-text' }

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

<div className="bg-section-title">⑤ 远端同步</div>
        {remoteSlug ? (
          <>
            <div className="sync-grid">
              <span className="dim">远端模板</span>
              <span className="mono">{remoteName || remoteSlug}</span>
              <span className="dim">所在库</span>
              <span className="mono">{libLabel}</span>
              <span className="dim">远端版本</span>
              <span className="mono">
                {remoteRev ? `第 ${remoteRev} 版` : '读不到'}
                {remoteUpdatedAt ? ` · ${remoteUpdatedAt.slice(0, 16).replace('T', ' ')}` : ''}
              </span>
              <span className="dim">本地记录</span>
              <span className="mono">第 {localRev || 1} 版</span>
              <span className="dim">状态</span>
              <span className={syncState.cls}>{syncState.text}</span>
            </div>
            <div className="row" style={{ marginTop: 8, gap: 8 }}>
              <button
                className="sm"
                disabled={!remoteChanged || updating}
                onClick={async () => {
                  setUpdating(true)
                  try {
                    const res = await api.loadCommunityTemplate(remoteSlug, {
                      mode: 'update',
                      canvasId: canvas!.id,
                    })
                    toast(`已更新到第 ${res.rev ?? '?'} 版`, 'ok')
                    await refreshCanvases()
                    await loadCanvas(canvas!.id)
                    onClose()
                  } catch (e: any) {
                    if (e?.status === 409 && e?.detail?.kind === 'local-changed') {
                      setSyncConflict(e.detail)
                      onClose()
                    } else {
                      toast(`更新失败：${e.message || e}`, 'err')
                    }
                  } finally {
                    setUpdating(false)
                  }
                }}
              >
                {updating ? '更新中…' : remoteChanged ? '拉取远端更新' : '已是最新'}
              </button>
              <span className="dim small">
                {localChanged ? '本地有未同步的改动' : '本地与远端一致'}
              </span>
            </div>
          </>
        ) : (
          <div className="hint-box">
            这张画布还没有关联远端模板。用「上传模板」推到公共库或私人库后，
            这里会显示它对应的模板、版本和更新状态。
          </div>
        )}

        <div className="hint-box" style={{ marginTop: 12 }}>
          这些是「整张画布怎么对外提供服务」的配置，不改变流程图本身；
          保存后会生成 <code className="mono">server.py</code>、<code className="mono">settings.py</code>、
          <code className="mono">telemetry.py</code>、<code className="mono">checkpoint.py</code>，
          以及对接外部中台的 <code className="mono">integrations/data_client.py</code>、
          <code className="mono">integrations/eval_client.py</code> 和 <code className="mono">integrations.json</code>。
          Token 只存环境变量名，不写进项目文件。
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
