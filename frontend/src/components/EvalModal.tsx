import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { useStore } from '../store'

/**
 * 评测中台：数据集 → 批量跑当前画布 → 规则 / LLM / 人工三层判定。
 *
 * 规则口径和生成项目里的 evals/run.py 一致（包含 / 排除 / 延迟），
 * 所以平台结果和项目自带回归脚本不会打架。
 */

type Tab = 'runs' | 'datasets' | 'report'

/** 外部评测上报的默认值：从画布服务设置里读，缺的用这套兜底 */
const DEFAULT_REPORT = {
  enabled: false,
  kind: 'http',
  base_url: '',
  auth: 'none',
  secret_ref: 'MINEAGENT_EVAL_TOKEN',
  project: '',
  evalsets: [] as { logical: string; remote: string }[],
  pass_rate: 0.8,
  latency_p95_ms: 0,
  report_on_run: true,
}

function evalsetsText(list: { logical: string; remote: string }[]): string {
  return (list || []).map((x) => `${x.logical} = ${x.remote}`).join('\n')
}

function parseEvalsets(text: string) {
  return text
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line && line.includes('='))
    .map((line) => {
      const [logical, ...rest] = line.split('=')
      return { logical: logical.trim(), remote: rest.join('=').trim() }
    })
}

const CASE_TEMPLATE = `# 每行一条用例，也可以整段贴 JSON 数组
{"id": "c1", "input": "用户会问的问题", "expect_contains": ["必须出现的词"], "expect_not_contains": [], "max_latency_ms": 15000}
{"id": "c2", "input": "另一条问题", "expect_contains": []}
`

function fmtPct(v: number | null | undefined): string {
  return v === null || v === undefined ? '—' : `${Math.round(v * 100)}%`
}

/** 后端存的是带时区的 ISO 串，这里统一成本地时间显示 */
function stamp(iso?: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return String(iso).slice(0, 19).replace('T', ' ')
  return d.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })
}

function duration(start?: string, end?: string): string {
  if (!start || !end) return '—'
  const a = new Date(start).getTime()
  const b = new Date(end).getTime()
  if (Number.isNaN(a) || Number.isNaN(b) || b < a) return '—'
  const sec = Math.round((b - a) / 1000)
  if (sec < 60) return `${sec}s`
  const min = Math.floor(sec / 60)
  return `${min}m ${sec % 60}s`
}

export default function EvalModal({ onClose }: { onClose: () => void }) {
  const toast = useStore((s) => s.toast)
  const canvas = useStore((s) => s.canvas)

  const [tab, setTab] = useState<Tab>('runs')
  const [datasets, setDatasets] = useState<any[]>([])
  const [runs, setRuns] = useState<any[]>([])
  const [loading, setLoading] = useState(true)

  // 新建数据集
  const [dsOpen, setDsOpen] = useState(false)
  const [dsName, setDsName] = useState('')
  const [dsDesc, setDsDesc] = useState('')
  const [dsCases, setDsCases] = useState(CASE_TEMPLATE)
  const [dsSaving, setDsSaving] = useState(false)

  // 发起评测
  const [datasetId, setDatasetId] = useState('')
  const [useJudge, setUseJudge] = useState(false)
  const [repeat, setRepeat] = useState(1)
  const [starting, setStarting] = useState(false)

  // 外部上报设置（存在画布服务设置的 eval 段里）
  const [report, setReport] = useState<any>(DEFAULT_REPORT)
  const [reportSaved, setReportSaved] = useState(false)

  // 选中的任务详情
  const [detail, setDetail] = useState<any>(null)
  const [trend, setTrend] = useState<any[]>([])
  const [baseId, setBaseId] = useState('')
  const [compare, setCompare] = useState<any>(null)
  const pollRef = useRef<number | null>(null)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  const refresh = async () => {
    setLoading(true)
    try {
      const [ds, rn] = await Promise.all([api.listDatasets(), api.listEvalRuns()])
      setDatasets(ds.items || [])
      setRuns(rn.items || [])
      if (!datasetId && ds.items?.length) setDatasetId(ds.items[0].id)
      // 趋势跟着当前画布走
      if (canvas?.id) {
        api
          .evalTrend({ canvas_id: canvas.id })
          .then((res) => setTrend(res.items || []))
          .catch(() => setTrend([]))
      } else {
        setTrend([])
      }
    } catch (e: any) {
      toast(`读取评测数据失败：${e.message || e}`, 'err')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    refresh()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 打开弹窗时把这张画布的上报设置读出来
  useEffect(() => {
    if (!canvas?.id) {
      setReport(DEFAULT_REPORT)
      return
    }
    api
      .getCanvas(canvas.id)
      .then((d) => {
        const svc = (d.graph as any)?.service || {}
        setReport({ ...DEFAULT_REPORT, ...(svc.eval || {}) })
      })
      .catch(() => setReport(DEFAULT_REPORT))
  }, [canvas?.id])

  const saveReport = async () => {
    if (!canvas) return
    try {
      await api.updateService(canvas.id, { eval: report })
      setReportSaved(true)
      window.setTimeout(() => setReportSaved(false), 2000)
      toast('上报设置已保存到画布服务设置', 'ok')
    } catch (e: any) {
      toast(`保存失败：${e.message || e}`, 'err')
    }
  }

  const patchReport = (key: string, value: any) =>
    setReport((prev: any) => ({ ...prev, [key]: value }))

  // 有正在跑的任务就轮询
  useEffect(() => {
    const running = runs.some((r) => r.status === 'running' || r.status === 'pending')
    if (!running) {
      if (pollRef.current) {
        window.clearInterval(pollRef.current)
        pollRef.current = null
      }
      return
    }
    if (pollRef.current) return
    pollRef.current = window.setInterval(() => {
      api
        .listEvalRuns()
        .then((res) => setRuns(res.items || []))
        .catch(() => {})
      if (detail?.id) {
        api
          .getEvalRun(detail.id)
          .then((res) => setDetail(res.run))
          .catch(() => {})
      }
    }, 2500)
    return () => {
      if (pollRef.current) {
        window.clearInterval(pollRef.current)
        pollRef.current = null
      }
    }
  }, [runs, detail?.id])

  const saveDataset = async () => {
    if (!dsName.trim()) {
      toast('给数据集起个名字', 'err')
      return
    }
    setDsSaving(true)
    try {
      const res = await api.createDataset({
        name: dsName.trim(),
        description: dsDesc,
        cases: dsCases,
      })
      toast(`数据集已保存（${res.dataset?.case_count || 0} 条用例）`, 'ok')
      setDsOpen(false)
      setDsName('')
      setDsDesc('')
      setDsCases(CASE_TEMPLATE)
      await refresh()
      if (res.dataset?.id) setDatasetId(res.dataset.id)
    } catch (e: any) {
      toast(`保存失败：${e.message || e}`, 'err')
    } finally {
      setDsSaving(false)
    }
  }

  const startRun = async () => {
    if (!canvas) {
      toast('先打开一张画布', 'err')
      return
    }
    if (!datasetId) {
      toast('先选一个数据集', 'err')
      return
    }
    setStarting(true)
    try {
      const res = await api.createEvalRun({
        canvas_id: canvas.id,
        dataset_id: datasetId,
        use_judge: useJudge,
        repeat,
      })
      toast('评测已开始，跑完会自动刷新', 'ok')
      await refresh()
      if (res.run?.id) {
        const d = await api.getEvalRun(res.run.id)
        setDetail(d.run)
      }
    } catch (e: any) {
      toast(`发起失败：${e.message || e}`, 'err')
    } finally {
      setStarting(false)
    }
  }

  const openRun = async (id: string) => {
    try {
      const d = await api.getEvalRun(id)
      setDetail(d.run)
      setBaseId('')
      setCompare(null)
    } catch (e: any) {
      toast(`读取结果失败：${e.message || e}`, 'err')
    }
  }

  const runCompare = async (id: string, base: string) => {
    setBaseId(base)
    if (!base) {
      setCompare(null)
      return
    }
    try {
      const res = await api.compareEvalRun(id, base)
      setCompare(res.compare)
    } catch (e: any) {
      toast(`对比失败：${e.message || e}`, 'err')
    }
  }

  const mark = async (resultId: string, verdict: string) => {
    try {
      await api.setEvalVerdict(resultId, verdict)
      if (detail?.id) {
        const d = await api.getEvalRun(detail.id)
        setDetail(d.run)
      }
    } catch (e: any) {
      toast(`标记失败：${e.message || e}`, 'err')
    }
  }

  const summary = detail?.summary

  return (
    <div className="kb-overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="kb-panel">
        <div className="kb-head">
          <div className="kb-head-left">
            <button className="ghost sm" onClick={onClose}>←</button>
            <span className="kb-title">评测中台</span>
            <span className="dim small">{canvas ? `当前画布：${canvas.name}` : '未打开画布'}</span>
          </div>
          <div className="kb-head-right">
            <div className="tabs" style={{ marginRight: 8 }}>
              <div className={`tab${tab === 'runs' ? ' active' : ''}`} onClick={() => setTab('runs')}>
                评测任务（{runs.length}）
              </div>
              <div className={`tab${tab === 'datasets' ? ' active' : ''}`} onClick={() => setTab('datasets')}>
                数据集（{datasets.length}）
              </div>
              <div className={`tab${tab === 'report' ? ' active' : ''}`} onClick={() => setTab('report')}>
                上报设置
              </div>
            </div>
            <button className="primary sm" onClick={() => setDsOpen(true)}>＋ 数据集</button>
          </div>
        </div>

        <div className="kb-body">
          {/* 趋势：这只画布历次通过率 */}
          {trend.length > 1 && (
            <div className="eval-trend">
              <span className="dim small">通过率趋势（{trend.length} 次）：</span>
              {trend.slice(-10).map((t, i) => (
                <span
                  key={t.id}
                  className="eval-trend-item"
                  title={`${t.created_at?.slice(0, 19)} · ${t.passed}/${t.total}`}
                >
                  <span
                    className="eval-trend-bar"
                    style={{
                      height: `${Math.max(4, Math.round((t.pass_rate || 0) * 26))}px`,
                      background:
                        t.pass_rate >= 1
                          ? 'var(--ok)'
                          : t.pass_rate >= 0.5
                            ? 'var(--warn)'
                            : 'var(--err)',
                    }}
                  />
                  {i === trend.slice(-10).length - 1 && (
                    <span className="dim small">{fmtPct(t.pass_rate)}</span>
                  )}
                </span>
              ))}
            </div>
          )}

          {/* 发起评测：只在任务页出现，数据集页不掺这个 */}
          {tab === 'runs' && (
            <div className="eval-launch">
              <div className="eval-launch-row">
                <label className="kb-field" style={{ minWidth: 220 }}>
                  <span>数据集</span>
                  <select value={datasetId} onChange={(e) => setDatasetId(e.target.value)}>
                    <option value="">选择数据集…</option>
                    {datasets.map((d) => (
                      <option key={d.id} value={d.id}>
                        {d.name}（{d.case_count} 条）
                      </option>
                    ))}
                  </select>
                </label>
                <label className="kb-field" style={{ minWidth: 96 }}>
                  <span>每条重复</span>
                  <input
                    type="number"
                    min={1}
                    max={5}
                    value={repeat}
                    onChange={(e) =>
                      setRepeat(Math.max(1, Math.min(5, Number(e.target.value) || 1)))
                    }
                    title="同一条用例跑几次，用来测非确定性"
                  />
                </label>
                <label className="eval-check">
                  <input
                    type="checkbox"
                    checked={useJudge}
                    onChange={(e) => setUseJudge(e.target.checked)}
                  />
                  启用 LLM 裁判（额外消耗模型额度）
                </label>
                <div style={{ flex: 1 }} />
                <button className="primary sm" disabled={starting || !canvas} onClick={startRun}>
                  {starting ? '发起中…' : '▶ 开始评测'}
                </button>
              </div>
            </div>
          )}

          {tab === 'runs' ? (
            <div className="eval-runs">
              {loading ? (
                <div className="kb-empty">读取中…</div>
              ) : runs.length === 0 ? (
                <div className="kb-empty">还没有评测任务。选个数据集，点「开始评测」。</div>
              ) : (
                <table className="eval-table">
                  <thead>
                    <tr>
                      <th>任务</th>
                      <th>数据集</th>
                      <th>状态</th>
                      <th>进度</th>
                      <th>规则通过</th>
                      <th>开始时间</th>
                      <th>结束时间</th>
                      <th>耗时</th>
                      <th>操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {runs.map((r) => (
                      <tr key={r.id}>
                        <td>{r.canvas_name}</td>
                        <td>{r.dataset_name}</td>
                        <td>
                          <span className={`kb-status kb-status-${r.status === 'done' ? 'ready' : r.status === 'failed' ? 'failed' : 'building'}`}>
                            {r.status}
                          </span>
                        </td>
                        <td>{r.done}/{r.total}</td>
                        <td>{r.total ? fmtPct(r.passed / r.total) : '—'}</td>
                        <td className="eval-time">{stamp(r.created_at)}</td>
                        <td className="eval-time">
                          {stamp(r.finished_at) || (r.status === 'running' ? '运行中…' : '—')}
                        </td>
                        <td className="eval-time">{duration(r.created_at, r.finished_at)}</td>
                        <td>
                          <button className="sm" onClick={() => openRun(r.id)}>查看</button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          ) : tab === 'report' ? (
            <div className="eval-report">
              <div className="dim small" style={{ marginBottom: 10 }}>
                把本画布的运行结果上报到**外部**评测系统（公司自建 / 第三方中台）。
                这里只配连接和映射，用例仍由对方管理。
              </div>
              <label className="row" style={{ gap: 8, marginBottom: 10 }}>
                <input
                  type="checkbox"
                  checked={!!report.enabled}
                  onChange={(e) => patchReport('enabled', e.target.checked)}
                  style={{ width: 15, height: 15 }}
                />
                <span className="small">启用外部评测上报</span>
              </label>
              <div className="kb-field-grid">
                <label className="kb-field">
                  <span>接入方式</span>
                  <select value={report.kind} onChange={(e) => patchReport('kind', e.target.value)}>
                    <option value="http">HTTP 评测 API</option>
                    <option value="sdk">自定义 SDK（模块名）</option>
                  </select>
                </label>
                <label className="kb-field">
                  <span>评测项目名</span>
                  <input
                    value={report.project}
                    placeholder="mineagent"
                    onChange={(e) => patchReport('project', e.target.value)}
                  />
                </label>
              </div>
              <label className="kb-field" style={{ marginTop: 8 }}>
                <span>Base URL</span>
                <input
                  value={report.base_url}
                  placeholder="https://eval.company.com"
                  onChange={(e) => patchReport('base_url', e.target.value)}
                />
              </label>
              <div className="kb-field-grid" style={{ marginTop: 8 }}>
                <label className="kb-field">
                  <span>认证方式</span>
                  <select value={report.auth} onChange={(e) => patchReport('auth', e.target.value)}>
                    <option value="none">无</option>
                    <option value="bearer">Bearer Token</option>
                    <option value="aksk">AK/SK</option>
                    <option value="oidc">OIDC</option>
                  </select>
                </label>
                <label className="kb-field">
                  <span>Token 环境变量名</span>
                  <input
                    value={report.secret_ref}
                    onChange={(e) => patchReport('secret_ref', e.target.value)}
                  />
                </label>
              </div>
              <label className="kb-field" style={{ marginTop: 8 }}>
                <span>评测集映射（每行：逻辑名 = 远程 ID）</span>
                <textarea
                  className="eval-cases-input"
                  rows={3}
                  value={evalsetsText(report.evalsets)}
                  placeholder="smoke = es_1024"
                  onChange={(e) => patchReport('evalsets', parseEvalsets(e.target.value))}
                />
              </label>
              <div className="kb-field-grid" style={{ marginTop: 8 }}>
                <label className="kb-field">
                  <span>通过率阈值（CI 门禁用）</span>
                  <input
                    type="number"
                    min={0}
                    max={1}
                    step={0.05}
                    value={report.pass_rate}
                    onChange={(e) => patchReport('pass_rate', Number(e.target.value))}
                  />
                </label>
                <label className="kb-field">
                  <span>P95 延迟阈值（ms）</span>
                  <input
                    type="number"
                    min={0}
                    value={report.latency_p95_ms}
                    onChange={(e) => patchReport('latency_p95_ms', Number(e.target.value))}
                  />
                </label>
              </div>
              <label className="row" style={{ gap: 8, marginTop: 10 }}>
                <input
                  type="checkbox"
                  checked={!!report.report_on_run}
                  onChange={(e) => patchReport('report_on_run', e.target.checked)}
                  style={{ width: 15, height: 15 }}
                />
                <span className="small">运行时自动上报（关闭则只在批量评测时上报）</span>
              </label>
              <div className="eval-foot">
                <span className="dim small">
                  保存在画布服务设置里，保存/运行时会编译进 integrations/eval_client.py
                </span>
                <button className="primary sm" onClick={saveReport}>
                  {reportSaved ? '已保存 ✓' : '保存上报设置'}
                </button>
              </div>
            </div>
          ) : (
            <div className="eval-runs">
              {datasets.length === 0 ? (
                <div className="kb-empty">
                  <div className="kb-empty-icon">▦</div>
                  <div style={{ marginBottom: 4 }}>还没有数据集</div>
                  <div className="dim small">
                    点右上角「＋ 数据集」，把用例贴进去就能建
                  </div>
                </div>
              ) : (
                <div className="kb-grid">
                  {datasets.map((d) => (
                    <div key={d.id} className="kb-card">
                      <div className="kb-card-top">
                        <span className="kb-card-icon">▦</span>
                        <span className="kb-status">{d.case_count} 条用例</span>
                      </div>
                      <div className="kb-card-name" title={d.name}>
                        {d.name}
                      </div>
                      <div className="dim small">{d.description || '—'}</div>
                      <div className="dim small">
                        更新于 {String(d.updated_at || '').slice(0, 19).replace('T', ' ')}
                      </div>
                      <div className="kb-card-actions">
                        <button
                          className="sm"
                          onClick={() => {
                            setDatasetId(d.id)
                            setTab('runs')
                            toast(`已选中「${d.name}」，可以直接开始评测`, 'ok')
                          }}
                        >
                          用它评测
                        </button>
                        <button
                          className="sm"
                          onClick={async () => {
                            if (!window.confirm(`删除数据集「${d.name}」？`)) return
                            await api.deleteDataset(d.id)
                            await refresh()
                          }}
                        >
                          删除
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* 结果详情 */}
          {/* 结果详情只属于任务页：切到数据集页就不该再露出来 */}
          {tab === 'runs' && detail && (
            <div className="eval-detail">
              <div className="eval-detail-head">
                <b>结果：{detail.canvas_name} · {detail.dataset_name}</b>
                <span className={`kb-status kb-status-${detail.status === 'done' ? 'ready' : 'building'}`}>
                  {detail.status}
                </span>
                <div style={{ flex: 1 }} />
                <label className="eval-check" style={{ paddingBottom: 0 }}>
                  对比基线
                  <select
                    value={baseId}
                    onChange={(e) => runCompare(detail.id, e.target.value)}
                    style={{
                      marginLeft: 6,
                      padding: '5px 8px',
                      borderRadius: 7,
                      border: '1px solid var(--border-soft)',
                      background: 'var(--panel)',
                      color: 'var(--text)',
                      fontSize: 12,
                    }}
                  >
                    <option value="">不对比</option>
                    {runs
                      .filter((r) => r.id !== detail.id && r.status === 'done')
                      .map((r) => (
                        <option key={r.id} value={r.id}>
                          {r.created_at?.slice(5, 19).replace('T', ' ')} · {r.canvas_name}
                        </option>
                      ))}
                  </select>
                </label>
                <button className="sm" onClick={() => setDetail(null)}>收起</button>
              </div>

              {compare && (
                <div className="eval-compare">
                  <div>
                    基线 <b>{fmtPct(compare.base.pass_rate)}</b> → 本次{' '}
                    <b>{fmtPct(compare.target.pass_rate)}</b>
                    <span className="dim small"> · 共同用例 {compare.common_cases}</span>
                  </div>
                  <div>
                    回归 <b style={{ color: 'var(--err)' }}>{compare.regressed.length}</b>
                    {compare.regressed.length > 0 && (
                      <span className="dim small">（{compare.regressed.slice(0, 6).join('、')}）</span>
                    )}
                    {'  '}
                    修复 <b style={{ color: 'var(--ok)' }}>{compare.fixed.length}</b>
                    {compare.fixed.length > 0 && (
                      <span className="dim small">（{compare.fixed.slice(0, 6).join('、')}）</span>
                    )}
                  </div>
                </div>
              )}
              {summary && (
                <>
                  <div className="eval-metrics">
                    <div className="eval-metric">
                      <span className="dim small">规则通过率</span>
                      <b>{fmtPct(summary.rule_pass_rate)}</b>
                      <span className="dim small">
                        {summary.rule_passed}/{summary.total} 次执行
                      </span>
                    </div>
                    <div className="eval-metric">
                      <span className="dim small">LLM 均分</span>
                      <b>{summary.judge_avg ?? '—'}</b>
                      <span className="dim small">{summary.judge_count} 条已评</span>
                    </div>
                    <div className="eval-metric">
                      <span className="dim small">人工通过率</span>
                      <b>{fmtPct(summary.human_pass_rate)}</b>
                      <span className="dim small">
                        {summary.human_reviewed}/{summary.total} 已复核
                      </span>
                    </div>
                    <div className="eval-metric">
                      <span className="dim small">延迟 p50 / p95</span>
                      <b>{Math.round(summary.latency?.p50 ?? 0)}ms</b>
                      <span className="dim small">
                        p95 {Math.round(summary.latency?.p95 ?? 0)}ms · p99{' '}
                        {Math.round(summary.latency?.p99 ?? 0)}ms
                      </span>
                    </div>
                  </div>

                  <div className="eval-metrics second">
                    <div className="eval-metric">
                      <span className="dim small">Token 用量</span>
                      <b>{summary.tokens?.total ?? 0}</b>
                      <span className="dim small">
                        入 {summary.tokens?.prompt ?? 0} · 出 {summary.tokens?.completion ?? 0}
                      </span>
                    </div>
                    <div className="eval-metric">
                      <span className="dim small">失败分类</span>
                      <b>
                        {(summary.failures?.run_error ?? 0) +
                          (summary.failures?.rule_failed ?? 0) +
                          (summary.failures?.timeout ?? 0)}
                      </b>
                      <span className="dim small">
                        跑挂 {summary.failures?.run_error ?? 0} · 不过{' '}
                        {summary.failures?.rule_failed ?? 0} · 超时{' '}
                        {summary.failures?.timeout ?? 0}
                      </span>
                    </div>
                    <div className="eval-metric">
                      <span className="dim small">稳定性</span>
                      <b>
                        {summary.stability
                          ? fmtPct(summary.stability.consistency_rate)
                          : '—'}
                      </b>
                      <span className="dim small">
                        {summary.stability
                          ? `${summary.stability.consistent_cases}/${summary.stability.repeated_cases} 用例多次一致`
                          : '单次执行，未测'}
                      </span>
                    </div>
                    <div className="eval-metric">
                      <span className="dim small">最大延迟</span>
                      <b>{Math.round(summary.latency?.max ?? 0)}ms</b>
                      <span className="dim small">
                        均值 {Math.round(summary.latency?.avg ?? 0)}ms
                      </span>
                    </div>
                  </div>

                  {summary.by_tag && Object.keys(summary.by_tag).length > 0 && (
                    <div className="eval-tags">
                      <span className="dim small">按标签：</span>
                      {Object.entries(summary.by_tag).map(([tag, v]: [string, any]) => (
                        <span key={tag} className="eval-tag">
                          {tag}
                          <b style={{ color: v.rate >= 1 ? 'var(--ok)' : v.rate > 0 ? 'var(--warn)' : 'var(--err)' }}>
                            {fmtPct(v.rate)}
                          </b>
                          <span className="dim small">{v.passed}/{v.total}</span>
                        </span>
                      ))}
                    </div>
                  )}
                </>
              )}
              <div className="eval-cases">
                {(detail.results || []).map((item: any) => (
                  <div key={item.id} className="eval-case">
                    <div className="eval-case-head">
                      <span className={`eval-dot ${item.rule_passed ? 'ok' : 'bad'}`} />
                      <b>{item.case_id}</b>
                      <span className="dim small">{Math.round(item.latency_ms)}ms</span>
                      {item.llm_score !== null && item.llm_score !== undefined && (
                        <span className="kb-badge">LLM {item.llm_score}</span>
                      )}
                      <div style={{ flex: 1 }} />
                      <button className="sm" onClick={() => mark(item.id, 'pass')}>通过</button>
                      <button className="sm" onClick={() => mark(item.id, 'fail')}>不通过</button>
                      {item.human_verdict && (
                        <span className={`kb-badge`} style={{ color: item.human_verdict === 'pass' ? 'var(--ok)' : 'var(--err)' }}>
                          人工：{item.human_verdict}
                        </span>
                      )}
                    </div>
                    <div className="dim small">输入：{item.input}</div>
                    <div className="eval-output">{item.output || '（无输出）'}</div>
                    {item.llm_reason && <div className="dim small">裁判：{item.llm_reason}</div>}
                    {item.error && <div className="kb-card-error">{item.error}</div>}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* 新建数据集 */}
        {dsOpen && (
          <div className="eval-sheet">
            <div className="eval-sheet-head">
              <b>新建数据集</b>
              <div style={{ flex: 1 }} />
              <button className="sm" onClick={() => setDsOpen(false)}>取消</button>
              <button className="primary sm" disabled={dsSaving} onClick={saveDataset}>
                {dsSaving ? '保存中…' : '保存'}
              </button>
            </div>
            <div className="kb-field-grid">
              <label className="kb-field">
                <span>名称 *</span>
                <input value={dsName} onChange={(e) => setDsName(e.target.value)} placeholder="例如：客服冒烟用例" />
              </label>
              <label className="kb-field">
                <span>说明</span>
                <input value={dsDesc} onChange={(e) => setDsDesc(e.target.value)} />
              </label>
            </div>
            <label className="kb-field" style={{ marginTop: 10 }}>
              <span>用例（JSONL 或 JSON 数组）</span>
              <textarea
                className="eval-cases-input"
                value={dsCases}
                onChange={(e) => setDsCases(e.target.value)}
                rows={12}
              />
            </label>
            <div className="dim small" style={{ marginTop: 6 }}>
              字段和项目里的 evals/cases.jsonl 一致：input、expect_contains、
              expect_not_contains、max_latency_ms、tags
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
