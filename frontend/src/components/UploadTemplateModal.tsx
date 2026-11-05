import { useEffect, useState } from 'react'
import { api } from '../api'
import { useStore } from '../store'
import Modal from './Modal'
import type { CommunityConfig } from '../types'

/**
 * 上传当前画布为社区模板：填写元信息 → 自动开 GitHub PR。
 * 上传内容自动剔除所有 API Key / 密钥字段。
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
  const [config, setConfig] = useState<CommunityConfig | null>(null)
  const [form, setForm] = useState({
    name: canvasName,
    description: '',
    tags: '',
    author: '',
  })
  const [publishing, setPublishing] = useState(false)
  const [prUrl, setPrUrl] = useState('')

  useEffect(() => {
    api
      .communityConfig()
      .then((conf) => {
        setConfig(conf)
        setForm((prev) => ({ ...prev, author: prev.author || conf.login || '' }))
      })
      .catch((e) => toast(String(e.message || e), 'err'))
  }, [toast])

  const publish = async () => {
    if (!form.name.trim()) {
      toast('请填写模板名称', 'info')
      return
    }
    setPublishing(true)
    try {
      const res = await api.publishTemplate({
        canvas_id: canvasId,
        name: form.name.trim(),
        description: form.description.trim(),
        tags: form.tags
          .split(/[,，]/)
          .map((s) => s.trim())
          .filter(Boolean),
        author: form.author.trim(),
      })
      setPrUrl(res.pr_url)
      toast('已创建 Pull Request，等待仓库维护者审批合并', 'ok')
    } catch (e: any) {
      toast(`上传失败：${e.message || e}`, 'err')
    } finally {
      setPublishing(false)
    }
  }

  return (
    <Modal
      title="上传为社区模板"
      subtitle="把当前画布和对应项目文件贡献到 GitHub 仓库，自动创建 Pull Request，由维护者审批合并。"
      onClose={onClose}
      width={640}
      footer={
        <>
          <button onClick={onClose}>{prUrl ? '关闭' : '取消'}</button>
          <div style={{ flex: 1 }} />
          {config && !config.connected && (
            <button onClick={onOpenCommunity}>去连接 GitHub</button>
          )}
          <button
            className="primary"
            onClick={publish}
            disabled={publishing || !config?.connected}
          >
            {publishing ? '正在上传…' : '上传并创建 PR'}
          </button>
        </>
      }
    >
      {config && !config.connected && (
        <div className="hint-box" style={{ borderColor: '#4a3c14', color: 'var(--warn)' }}>
          还没有连接 GitHub。先在「用户中心 → 社区模板」里配置仓库并登录，才能自动创建 Pull Request。
        </div>
      )}

      <label className="field">
        <span>模板名称</span>
        <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
      </label>
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
        提交后是一个 PR，需要仓库维护者在 GitHub 上审批通过才会合并。
      </div>

      {prUrl && (
        <div className="hint-box" style={{ borderColor: '#1d4b3b', color: 'var(--ok)' }}>
          已创建 Pull Request：
          <a href={prUrl} target="_blank" rel="noreferrer" className="mono">
            {prUrl}
          </a>
        </div>
      )}
    </Modal>
  )
}
