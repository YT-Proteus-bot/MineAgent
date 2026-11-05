import { useEffect, useState } from 'react'
import { api } from '../api'
import { useStore } from '../store'
import Modal from './Modal'
import type { CommunityConfig, CommunityTemplate } from '../types'

/**
 * 社区模板：GitHub 连接配置 + 公开模板列表 + 一键加载成新画布。
 * GitHub 登录走 OAuth 授权码流程，回调后回到首页并带 ?github=connected。
 */
export default function CommunityModal({
  onClose,
  onLoaded,
}: {
  onClose: () => void
  onLoaded?: (canvasId: string) => void
}) {
  const toast = useStore((s) => s.toast)
  const [config, setConfig] = useState<CommunityConfig | null>(null)
  const [templates, setTemplates] = useState<CommunityTemplate[]>([])
  const [form, setForm] = useState({
    repo: '',
    branch: 'main',
    dir: 'templates',
    client_id: '',
    client_secret: '',
  })
  const [saving, setSaving] = useState(false)
  const [loadingSlug, setLoadingSlug] = useState('')

  const refresh = async () => {
    try {
      const conf = await api.communityConfig()
      setConfig(conf)
      setForm({
        repo: conf.repo,
        branch: conf.branch,
        dir: conf.dir,
        client_id: conf.client_id,
        client_secret: '',
      })
      const res = await api.communityTemplates()
      setTemplates(res.templates || [])
    } catch (e: any) {
      toast(String(e.message || e), 'err')
    }
  }

  useEffect(() => {
    refresh()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const save = async () => {
    setSaving(true)
    try {
      await api.saveCommunityConfig(form)
      await refresh()
      toast('社区模板配置已保存', 'ok')
    } catch (e: any) {
      toast(`保存失败：${e.message || e}`, 'err')
    } finally {
      setSaving(false)
    }
  }

  const connect = async () => {
    try {
      const { url } = await api.communityAuthUrl()
      window.location.href = url
    } catch (e: any) {
      toast(String(e.message || e), 'err')
    }
  }

  const disconnect = async () => {
    try {
      await api.communityDisconnect()
      await refresh()
      toast('已断开 GitHub', 'ok')
    } catch (e: any) {
      toast(String(e.message || e), 'err')
    }
  }

  const load = async (tpl: CommunityTemplate) => {
    setLoadingSlug(tpl.slug)
    try {
      const res = await api.loadCommunityTemplate(tpl.slug)
      toast(`已把「${tpl.name}」加载成新画布`, 'ok')
      onLoaded?.(res.canvas.id)
      onClose()
    } catch (e: any) {
      toast(`加载失败：${e.message || e}`, 'err')
    } finally {
      setLoadingSlug('')
    }
  }

  return (
    <Modal
      title="社区模板"
      subtitle="连上 GitHub 之后，可以把别人的模板一键加载成画布，也可以把自己设计的画布提 PR 分享出去。"
      onClose={onClose}
      width={760}
      footer={
        <>
          <button onClick={onClose}>关闭</button>
          <div style={{ flex: 1 }} />
          <button className="primary" onClick={save} disabled={saving}>
            {saving ? '保存中…' : '保存连接配置'}
          </button>
        </>
      }
    >
      <div className="community-connect">
        <div className="row" style={{ gap: 8 }}>
          <span className="dim small">GitHub 登录</span>
          {config?.connected ? (
            <span className="badge ok">已连接 @{config.login || 'github'}</span>
          ) : (
            <span className="badge warn">未连接</span>
          )}
          <div style={{ flex: 1 }} />
          {config?.connected ? (
            <button className="sm" onClick={disconnect}>
              断开
            </button>
          ) : (
            <button className="sm primary" onClick={connect} disabled={!config?.client_id}>
              连接 GitHub
            </button>
          )}
        </div>
        <div className="dim small" style={{ marginTop: 6, lineHeight: 1.7 }}>
          回调地址要填到 GitHub OAuth App 里：
          <code className="mono">{config?.callback_url}</code>
        </div>
      </div>

      <div className="row" style={{ gap: 10 }}>
        <label className="field" style={{ flex: 1 }}>
          <span>模板仓库（owner/repo）</span>
          <input
            value={form.repo}
            placeholder="yourname/MineAgent-Templates"
            onChange={(e) => setForm({ ...form, repo: e.target.value })}
          />
        </label>
        <label className="field" style={{ width: 110 }}>
          <span>分支</span>
          <input value={form.branch} onChange={(e) => setForm({ ...form, branch: e.target.value })} />
        </label>
        <label className="field" style={{ width: 130 }}>
          <span>模板目录</span>
          <input value={form.dir} onChange={(e) => setForm({ ...form, dir: e.target.value })} />
        </label>
      </div>

      <div className="row" style={{ gap: 10 }}>
        <label className="field" style={{ flex: 1 }}>
          <span>OAuth Client ID</span>
          <input
            value={form.client_id}
            placeholder="在 GitHub → Settings → Developer settings → OAuth Apps 里创建"
            onChange={(e) => setForm({ ...form, client_id: e.target.value })}
          />
        </label>
        <label className="field" style={{ flex: 1 }}>
          <span>Client Secret</span>
          <input
            type="password"
            value={form.client_secret}
            autoComplete="off"
            placeholder={config?.client_secret_mask ? `已保存 ${config.client_secret_mask}（留空不改）` : '只保存在本机，加密存储'}
            onChange={(e) => setForm({ ...form, client_secret: e.target.value })}
          />
        </label>
      </div>

      <div className="community-head">
        <span>公开模板</span>
        <span className="dim small">
          {config?.repo ? `来自 ${config.repo} · ${config.branch} · ${config.dir}` : '配置仓库后这里会出现模板'}
        </span>
        <div style={{ flex: 1 }} />
        <button className="sm" onClick={refresh}>
          刷新
        </button>
      </div>

      <div className="community-list">
        {templates.length === 0 && (
          <div className="dim" style={{ padding: '14px 0' }}>
            还没有可加载的模板。确认仓库、分支、模板目录填对之后点「刷新」。
          </div>
        )}
        {templates.map((t) => (
          <div key={t.slug} className="community-item">
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className="row" style={{ gap: 6 }}>
                <b>{t.name}</b>
                {t.framework && <span className="badge">{t.framework}</span>}
                {t.mode && <span className="badge">{t.mode}</span>}
              </div>
              {t.description && (
                <div className="dim small" style={{ marginTop: 3, lineHeight: 1.6 }}>
                  {t.description}
                </div>
              )}
              <div className="dim small" style={{ marginTop: 3 }}>
                {t.author || '匿名'} · {t.node_count} 节点
                {t.created_at ? ` · ${String(t.created_at).slice(0, 10)}` : ''}
                {t.tags?.length ? ` · ${t.tags.join(' / ')}` : ''}
              </div>
            </div>
            <button className="primary sm" onClick={() => load(t)} disabled={!!loadingSlug}>
              {loadingSlug === t.slug ? <span className="spin" /> : '加载'}
            </button>
          </div>
        ))}
      </div>
    </Modal>
  )
}
