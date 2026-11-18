import { useEffect, useState } from 'react'
import { useStore } from '../store'
import { api } from '../api'
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
    data: { ...DEFAULT_SERVICE.data, ...(raw?.data || {}) },
    eval: { ...DEFAULT_SERVICE.eval, ...(raw?.eval || {}) },
  }
}

function datasetsText(list: { logical: string; physical: string; mode: string }[]): string {
  return (list || [])
    .map((d) => `${d.logical} = ${d.physical}${d.mode === 'write' ? ':write' : ''}`)
    .join('\n')
}

function parseDatasets(text: string) {
  return text
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const idx = line.indexOf('=')
      const logical = (idx >= 0 ? line.slice(0, idx) : line).trim()
      let physical = (idx >= 0 ? line.slice(idx + 1) : '').trim()
      let mode = 'read'
      if (physical.endsWith(':write')) {
        mode = 'write'
        physical = physical.slice(0, -6).trim()
      }
      return { logical, physical, mode }
    })
    .filter((d) => d.logical)
}

function evalsetsText(list: { logical: string; remote: string }[]): string {
  return (list || []).map((e) => `${e.logical} = ${e.remote}`).join('\n')
}

function parseEvalsets(text: string) {
  return text
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const idx = line.indexOf('=')
      const logical = (idx >= 0 ? line.slice(0, idx) : line).trim()
      const remote = (idx >= 0 ? line.slice(idx + 1) : '').trim()
      return { logical, remote }
    })
    .filter((e) => e.logical)
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

        <div className="bg-section-title" style={{ marginTop: 14 }}>
          ⑤ 数据中台（外部）
        </div>
        <label className="row" style={{ gap: 8 }}>
          <input
            type="checkbox"
            checked={form.data.enabled}
            onChange={(e) => patch('data', 'enabled', e.target.checked)}
            style={{ width: 15, height: 15 }}
          />
          <span className="small">启用外部数据中台（默认只读，写入需单独标 :write）</span>
        </label>
        <label className="field">
          <span>接入方式</span>
          <select value={form.data.kind} onChange={(e) => patch('data', 'kind', e.target.value)}>
            <option value="http">HTTP 数据集 API</option>
            <option value="sdk">自定义 SDK（模块名）</option>
            <option value="jdbc">JDBC（需额外依赖）</option>
            <option value="s3">S3 兼容（需额外依赖）</option>
          </select>
        </label>
        <label className="field">
          <span>Base URL</span>
          <input
            value={form.data.base_url}
            placeholder="https://data.company.com"
            onChange={(e) => patch('data', 'base_url', e.target.value)}
          />
        </label>
        <div className="row" style={{ gap: 10 }}>
          <label className="field" style={{ flex: 1 }}>
            <span>认证</span>
            <select value={form.data.auth} onChange={(e) => patch('data', 'auth', e.target.value)}>
              <option value="none">无</option>
              <option value="bearer">Bearer Token</option>
              <option value="aksk">AK/SK</option>
              <option value="oidc">OIDC</option>
            </select>
          </label>
          <label className="field" style={{ flex: 1 }}>
            <span>Token 环境变量名</span>
            <input
              value={form.data.secret_ref}
              onChange={(e) => patch('data', 'secret_ref', e.target.value)}
            />
          </label>
        </div>
        <label className="field">
          <span>数据集映射（每行：逻辑名 = 物理表 / 路径，写权限加 :write）</span>
          <textarea
            rows={4}
            className="mono"
            value={datasetsText(form.data.datasets)}
            placeholder="customer_orders = dwd.customer_orders"
            onChange={(e) =>
              setForm((f) => ({ ...f, data: { ...f.data, datasets: parseDatasets(e.target.value) } }))
            }
          />
        </label>
        <div className="row" style={{ gap: 10 }}>
          <label className="field" style={{ flex: 1 }}>
            <span>超时（秒）</span>
            <input
              type="number"
              min={5}
              value={form.data.timeout_s}
              onChange={(e) => patch('data', 'timeout_s', Number(e.target.value))}
            />
          </label>
          <label className="field" style={{ flex: 1 }}>
            <span>脱敏字段（逗号分隔）</span>
            <input
              value={(form.data.pii_fields || []).join(', ')}
              placeholder="phone, id_card"
              onChange={(e) =>
                patch(
                  'data',
                  'pii_fields',
                  e.target.value.split(',').map((s) => s.trim()).filter(Boolean),
                )
              }
            />
          </label>
        </div>

        <div className="bg-section-title" style={{ marginTop: 14 }}>
          ⑥ 评测中台（外部）
        </div>
        <label className="row" style={{ gap: 8 }}>
          <input
            type="checkbox"
            checked={form.eval.enabled}
            onChange={(e) => patch('eval', 'enabled', e.target.checked)}
            style={{ width: 15, height: 15 }}
          />
          <span className="small">启用外部评测中台（评测集由中台管理，这里只做映射）</span>
        </label>
        <label className="field">
          <span>接入方式</span>
          <select value={form.eval.kind} onChange={(e) => patch('eval', 'kind', e.target.value)}>
            <option value="http">HTTP 评测 API</option>
            <option value="sdk">自定义 SDK（模块名）</option>
          </select>
        </label>
        <label className="field">
          <span>Base URL</span>
          <input
            value={form.eval.base_url}
            placeholder="https://eval.company.com"
            onChange={(e) => patch('eval', 'base_url', e.target.value)}
          />
        </label>
        <div className="row" style={{ gap: 10 }}>
          <label className="field" style={{ flex: 1 }}>
            <span>认证</span>
            <select value={form.eval.auth} onChange={(e) => patch('eval', 'auth', e.target.value)}>
              <option value="none">无</option>
              <option value="bearer">Bearer Token</option>
              <option value="aksk">AK/SK</option>
              <option value="oidc">OIDC</option>
            </select>
          </label>
          <label className="field" style={{ flex: 1 }}>
            <span>Token 环境变量名</span>
            <input
              value={form.eval.secret_ref}
              onChange={(e) => patch('eval', 'secret_ref', e.target.value)}
            />
          </label>
        </div>
        <label className="field">
          <span>评测项目名</span>
          <input
            value={form.eval.project}
            placeholder="mineagent"
            onChange={(e) => patch('eval', 'project', e.target.value)}
          />
        </label>
        <label className="field">
          <span>评测集映射（每行：逻辑名 = 远程 ID）</span>
          <textarea
            rows={3}
            className="mono"
            value={evalsetsText(form.eval.evalsets)}
            placeholder="smoke = es_1024"
            onChange={(e) =>
              setForm((f) => ({ ...f, eval: { ...f.eval, evalsets: parseEvalsets(e.target.value) } }))
            }
          />
        </label>
        <div className="row" style={{ gap: 10 }}>
          <label className="field" style={{ flex: 1 }}>
            <span>通过率阈值（CI 门禁用）</span>
            <input
              type="number"
              min={0}
              max={1}
              step={0.05}
              value={form.eval.pass_rate}
              onChange={(e) => patch('eval', 'pass_rate', Number(e.target.value))}
            />
          </label>
          <label className="field" style={{ flex: 1 }}>
            <span>P95 延迟阈值（ms）</span>
            <input
              type="number"
              min={0}
              value={form.eval.latency_p95_ms}
              onChange={(e) => patch('eval', 'latency_p95_ms', Number(e.target.value))}
            />
          </label>
        </div>
        <label className="row" style={{ gap: 8 }}>
          <input
            type="checkbox"
            checked={form.eval.report_on_run}
            onChange={(e) => patch('eval', 'report_on_run', e.target.checked)}
            style={{ width: 15, height: 15 }}
          />
          <span className="small">运行时自动上报（关闭则只在批量评测时上报）</span>
        </label>

        <div className="bg-section-title">⑥ 远端同步</div>
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
