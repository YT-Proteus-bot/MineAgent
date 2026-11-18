import { useEffect, useState } from 'react'
import { api } from '../api'
import { useStore } from '../store'
import Modal from './Modal'
import type { CanvasSummary, CommunityConfig, TemplateLib } from '../types'

interface TplInfo {
  slug?: string
  name: string
  canvas_id?: string
  canvas_updated_at?: string
  graph_hash?: string
  node_count?: number
  created_at?: string
}

interface PrInfo {
  name: string
  canvas_id?: string
  state: 'open' | 'merged' | 'closed'
  pr_number: number
  pr_url: string
  created_at?: string
}

/**
 * 上传画布为模板：选画布 + 选模板库 → 公共库走 PR，私人库直接提交。
 * 下拉里同时显示版本关系、该画布 PR 状态。
 */
export default function UploadTemplateModal({
  canvasId,
  canvasName,
  onClose,
  onOpenCommunity,
}: {
  canvasId: string
  canvasName: string
  onClose: () => void
  onOpenCommunity?: () => void
}) {
  const toast = useStore((s) => s.toast)
  const startUpload = useStore((s) => s.startUpload)
  const uploadJobs = useStore((s) => s.uploadJobs)
  const canvases = useStore((s) => s.canvases)
  const [config, setConfig] = useState<CommunityConfig | null>(null)
  const [selectedId, setSelectedId] = useState(canvasId)
  const [templates, setTemplates] = useState<TplInfo[]>([])
  const [prs, setPrs] = useState<PrInfo[]>([])
  const [libs, setLibs] = useState<TemplateLib[]>([])
  const [libId, setLibId] = useState('')
  const [form, setForm] = useState({
    name: canvasName,
    description: '',
    tags: '',
    author: '',
  })

  const selected = canvases.find((c) => c.id === selectedId)
  const lib = libs.find((l) => l.id === libId)

  const chooseCanvas = (id: string) => {
    setSelectedId(id)
    const found = canvases.find((c) => c.id === id)
    if (found) setForm((prev) => ({ ...prev, name: found.name }))
  }

  useEffect(() => {
    api
      .communityConfig()
      .then((conf) => {
        setConfig(conf)
        setForm((prev) => ({ ...prev, author: prev.author || conf.login || '' }))
      })
      .catch((e) => toast(String(e.message || e), 'err'))
    api
      .communityCanvasStatus()
      .then((res) => {
        setTemplates(res.templates || [])
        setPrs(res.prs || [])
      })
      .catch(() => {})
    api
      .communityLibs()
      .then((res) => {
        setLibs(res.libs || [])
        if ((res.libs || []).length > 0) setLibId((prev) => prev || res.libs[0].id)
      })
      .catch(() => {})
  }, [toast])

  // 每张画布可以绑定一个私人库；切画布时读它的绑定
  useEffect(() => {
    if (!selectedId) return
    api
      .canvasLib(selectedId)
      .then((res) => {
        if (res.lib_id) setLibId(res.lib_id)
      })
      .catch(() => {})
  }, [selectedId])

  const tplFor = (c: CanvasSummary): TplInfo | undefined =>
    templates.find((t) => t.canvas_id && t.canvas_id === c.id) ||
    templates.find((t) => !t.canvas_id && t.name === c.name)

  const prFor = (c: CanvasSummary): PrInfo | undefined =>
    prs
      .filter((p) => (p.canvas_id ? p.canvas_id === c.id : p.name === c.name))
      .sort((a, b) => b.pr_number - a.pr_number)[0]

  const versionHint = (c: CanvasSummary): string => {
    const t = tplFor(c)
    if (!t) return ''
    if (t.canvas_updated_at) {
      if (c.updated_at > t.canvas_updated_at) return '本地领先'
      if (c.updated_at < t.canvas_updated_at) return '模板更新'
      return '已同步'
    }
    if (typeof t.node_count === 'number' && t.node_count !== c.node_count) {
      return c.node_count > t.node_count ? '本地领先' : '模板更新'
    }
    return ''
  }

  const prHint = (c: CanvasSummary): string => {
    const p = prFor(c)
    if (!p) return ''
    if (p.state === 'open') return `PR #${p.pr_number} 待合入`
    if (p.state === 'merged') return `PR #${p.pr_number} 已合入`
    return `PR #${p.pr_number} 已关闭`
  }

  const uploading = uploadJobs.some(
    (j) => j.canvasId === selectedId && j.status === 'running',
  )
  const selectedPr = selected ? prFor(selected) : undefined
  const selectedTpl = selected ? tplFor(selected) : undefined
  const selectedVersion = selected ? versionHint(selected) : ''
  // 「待合入」只对公共库有意义；私人库直接提交，不查 PR
  const selectedPending =
    lib?.kind === 'public' &&
    ((!!selectedPr && selectedPr.state === 'open') ||
      uploadJobs.some((j) => j.canvasId === selectedId && j.status === 'ok'))
  const noLib = !libId || !lib

  const publish = () => {
    if (!selectedId) {
      toast('请选择要上传的画布', 'info')
      return
    }
    if (noLib) {
      toast('先到用户中心 → 模板库配置一个模板库', 'info')
      return
    }
    if (selectedPending) {
      toast('这张画布已上传待合入，请到 GitHub 撤销 PR 或等待合入', 'info')
      return
    }
    if (uploading) {
      toast('这张画布正在上传中，可以换一张画布继续传', 'info')
      return
    }
    const name = (form.name || selected?.name || '').trim()
    if (!name) {
      toast('这张画布还没有名称', 'info')
      return
    }
    startUpload({
      canvas_id: selectedId,
      name,
      description: form.description.trim(),
      tags: form.tags
        .split(/[,，]/)
        .map((s) => s.trim())
        .filter(Boolean),
      author: form.author.trim(),
      lib_id: libId,
    })
    toast(
      lib?.kind === 'private'
        ? `「${name}」已提交到私人库「${lib.name}」，任务在后台继续`
        : `「${name}」已提交到「${lib?.name || '公共库'}」，任务在后台继续`,
      'info',
    )
  }

  return (
    <Modal
      title="上传为模板"
      subtitle="选画布 + 模板库：公共库走 PR 审核，私人库直接提交到团队仓库。"
      onClose={onClose}
      width={680}
      footer={
        <>
          <button onClick={onClose}>取消</button>
          <div style={{ flex: 1 }} />
          {config && !config.connected && (
            <button onClick={onOpenCommunity}>去连接 GitHub</button>
          )}
          <button
            className="primary"
            onClick={publish}
            disabled={!config?.connected || uploading || selectedPending || noLib}
          >
            {selectedPending
              ? '已上传待合入'
              : noLib
                ? '先配置模板库'
                : uploading
                  ? '这张画布上传中…'
                  : lib?.kind === 'private'
                    ? '提交到私人库'
                    : '上传并创建 PR'}
          </button>
        </>
      }
    >
      {config && !config.connected && (
        <div className="hint-box" style={{ borderColor: '#4a3c14', color: 'var(--warn)' }}>
          还没有连接 GitHub。先在「用户中心 → 模板库」里连接并配置仓库，才能上传。
        </div>
      )}

      <label className="field">
        <span>选择画布</span>
        <select value={selectedId} onChange={(e) => chooseCanvas(e.target.value)}>
          {canvases.map((c) => {
            const v = versionHint(c)
            const p = prHint(c)
            const pending =
              (prFor(c)?.state === 'open') ||
              uploadJobs.some((j) => j.canvasId === c.id && j.status === 'ok')
            return (
              <option key={c.id} value={c.id}>
                {c.name}（{c.framework}）
                {v ? ` · ${v}` : ''}
                {p ? ` · ${p}` : ''}
                {pending && !p ? ' · 已上传待合入' : ''}
              </option>
            )
          })}
        </select>
        <span className="dim small" style={{ marginTop: 4 }}>
          {selected ? `模板名称：${selected.name}` : '没有可选画布'}
          {selectedTpl?.created_at ? ` · 公共模板更新于 ${selectedTpl.created_at.slice(0, 10)}` : ''}
        </span>
      </label>

      <div className="row" style={{ gap: 10, marginBottom: 8 }}>
        <label className="field" style={{ flex: 1 }}>
          <span>上传到</span>
          <select value={libId} onChange={(e) => setLibId(e.target.value)}>
            {libs.map((l) => (
              <option key={l.id} value={l.id}>
                {l.name || l.repo}（{l.kind === 'private' ? '私人' : '公共'} · {l.repo}）
              </option>
            ))}
            {libs.length === 0 && <option value="">还没有模板库</option>}
          </select>
        </label>
        <div className="row" style={{ gap: 8, alignSelf: 'flex-end', paddingBottom: 2 }}>
          <button
            className="sm"
            disabled={!libId}
            onClick={async () => {
              try {
                await api.saveCanvasLib(selectedId, libId)
                toast('已设为这张画布的默认模板库', 'ok')
              } catch (e: any) {
                toast(`保存失败：${e.message || e}`, 'err')
              }
            }}
          >
            设为默认库
          </button>
        </div>
      </div>

      {noLib && (
        <div className="hint-box" style={{ borderColor: '#4a3c14', color: 'var(--warn)', marginBottom: 10 }}>
          还没有模板库。先到「用户中心 → 模板库」添加一个公共或私人仓库。
        </div>
      )}

      {selectedPending && (
        <div className="hint-box" style={{ borderColor: '#4a3c14', color: 'var(--warn)', marginBottom: 10 }}>
          这张画布已经上传过，PR 还没合入，不能重复上传。请到 GitHub 撤销 PR 或等待合入。
        </div>
      )}

      {!selectedPending && selectedPr && selectedPr.state === 'merged' && selectedVersion === '本地领先' && (
        <div className="hint-box" style={{ borderColor: '#1d4b3b', color: 'var(--ok)', marginBottom: 10 }}>
          上次 PR #{selectedPr.pr_number} 已合入；本地画布有更新，可以再上传一个新版本。
        </div>
      )}

      <label className="field">
        <span>一句话描述</span>
        <textarea
          rows={3}
          value={form.description}
          placeholder="这个模板解决什么问题、适合什么场景…"
          onChange={(e) => setForm({ ...form, description: e.target.value })}
        />
      </label>
      <div className="row" style={{ gap: 10 }}>
        <label className="field" style={{ flex: 1 }}>
          <span>标签（逗号分隔）</span>
          <input
            value={form.tags}
            placeholder="RAG, 客服, 多智能体"
            onChange={(e) => setForm({ ...form, tags: e.target.value })}
          />
        </label>
        <label className="field" style={{ flex: 1 }}>
          <span>署名</span>
          <input
            value={form.author}
            placeholder="默认用 GitHub 用户名"
            onChange={(e) => setForm({ ...form, author: e.target.value })}
          />
        </label>
      </div>

      <div className="hint-box">
        会上传：画布 JSON（节点 / 连线 / 参数）+ 项目里的 <code className="mono">agent.py</code>、
        <code className="mono">agent.json</code>、<code className="mono">config.json</code>、README 等白名单文件。
        <br />
        <b>不会上传</b>：任何 API Key、OAuth token、<code className="mono">.env</code>、模型密钥字段，上传前会统一剔除。
        <br />
        公共库会创建一个 PR 等待维护者合并；私人库直接提交到配置的分支。
        <br />
        点击上传后弹窗不会关闭，任务在后台继续，可以接着选别的画布；进度在左下角「上传任务」里看。
      </div>
    </Modal>
  )
}
