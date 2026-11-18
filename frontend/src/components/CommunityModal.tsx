import { useEffect, useState } from 'react'
import { api } from '../api'
import { useStore } from '../store'
import Modal from './Modal'
import type { CommunityConfig, CommunityTemplate, TemplateLib } from '../types'

/**
 * 浏览模板库并一键加载成新画布。
 * 仓库配置统一在「用户中心 → GitHub 账户 → 仓库设置」里，这里只读。
 */
export default function CommunityModal({
  onClose,
  onLoaded,
}: {
  onClose: () => void
  onLoaded?: (canvasId: string) => void
}) {
  const toast = useStore((s) => s.toast)
  const canvas = useStore((s) => s.canvas)
  const [config, setConfig] = useState<CommunityConfig | null>(null)
  const [libs, setLibs] = useState<TemplateLib[]>([])
  const [libId, setLibId] = useState('')
  const [templates, setTemplates] = useState<CommunityTemplate[]>([])
  const [count, setCount] = useState(0)
  const [loadingSlug, setLoadingSlug] = useState('')
  const [loadingList, setLoadingList] = useState(false)

  useEffect(() => {
    api
      .communityConfig()
      .then(setConfig)
      .catch(() => {})
    api
      .communityLibs()
      .then((res) => {
        const list = res.libs || []
        setLibs(list)
        if (list.length > 0) setLibId(list[0].id)
      })
      .catch(() => {})
  }, [])

  useEffect(() => {
    if (!libId) {
      setTemplates([])
      setCount(0)
      return
    }
    setLoadingList(true)
    // 先只列目录拿数量（一次请求，快）；再拉每个模板的 meta（并发）
    api
      .libCount(libId)
      .then((res) => setCount(res.count || 0))
      .catch(() => {})
    api
      .libTemplates(libId)
      .then((res) => {
        setTemplates(res.templates || [])
        setCount((res.templates || []).length)
      })
      .catch(() => setTemplates([]))
      .finally(() => setLoadingList(false))
  }, [libId])

  const load = async (tpl: CommunityTemplate) => {
    setLoadingSlug(tpl.slug)
    try {
      const res = await api.libLoad(libId, tpl.slug)
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
      title="模板库"
      subtitle="从公共 / 私人模板库里挑一个，一键加载成新画布。仓库在「用户中心 → GitHub 账户 → 仓库设置」里配置。"
      onClose={onClose}
      width={760}
      footer={<button onClick={onClose}>关闭</button>}
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
        </div>
      </div>

      <div className="community-head" style={{ marginTop: 10 }}>
        <span>选择模板库</span>
        <select value={libId} onChange={(e) => setLibId(e.target.value)} style={{ width: 280 }}>
          {libs.map((lib) => (
            <option key={lib.id} value={lib.id}>
              {lib.name || lib.repo}（{lib.kind === 'private' ? '私人' : '公共'} · {lib.repo}）
            </option>
          ))}
          {libs.length === 0 && <option value="">还没有配置模板库</option>}
        </select>
        <span className="dim small">{count} 个模板</span>
        <span className="dim small">{canvas ? `当前画布：${canvas.name}` : '先打开一张画布'}</span>
        <div style={{ flex: 1 }} />
        <button
          className="sm"
          onClick={() => {
            if (!libId) return
            setLoadingList(true)
            api
              .libTemplates(libId, true)
              .then((r) => setTemplates(r.templates || []))
              .catch(() => {})
              .finally(() => setLoadingList(false))
          }}
        >
          刷新
        </button>
      </div>

      <div className="community-list">
        {loadingList && (
          <div className="dim" style={{ padding: '14px 0' }}>
            <span className="spin" style={{ marginRight: 8, verticalAlign: -2 }} />
            正在加载模板…
          </div>
        )}
        {!loadingList && templates.length === 0 && (
          <div className="dim" style={{ padding: '14px 0' }}>
            {libs.length === 0
              ? '还没有配置模板库。先到「用户中心 → GitHub 账户 → 仓库设置」添加一个。'
              : '这个库里还没有模板。'}
          </div>
        )}
        {!loadingList &&
          templates.map((t) => (
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
