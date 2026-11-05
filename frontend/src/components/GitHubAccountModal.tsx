import { useEffect, useState } from 'react'
import { api } from '../api'
import { useStore } from '../store'
import type { CommunityConfig } from '../types'
import Modal from './Modal'

/**
 * GitHub 账户：连接 / 断开 / 查看当前登录身份。
 * 登录走 OAuth 授权码流程，回调后回到首页并带 ?github=connected。
 */
export default function GitHubAccountModal({ onClose }: { onClose: () => void }) {
  const toast = useStore((s) => s.toast)
  const [config, setConfig] = useState<CommunityConfig | null>(null)
  const [busy, setBusy] = useState(false)
  const [advanced, setAdvanced] = useState(false)
  const [form, setForm] = useState({ client_id: '', client_secret: '', repo: '', branch: 'main', dir: 'templates' })

  const reload = async () => {
    try {
      const c = await api.communityConfig()
      setConfig(c)
      setForm((f) => ({
        ...f,
        client_id: f.client_id || c.client_id || '',
        repo: f.repo || c.repo || '',
        branch: c.branch || 'main',
        dir: c.dir || 'templates',
      }))
    } catch (e: any) {
      toast(`读取配置失败：${e.message || e}`, 'err')
    }
  }

  useEffect(() => {
    reload()
  }, [])

  const connect = async () => {
    if (!config?.client_id) {
      setAdvanced(true)
      toast('先填 GitHub OAuth 的 Client ID 和 Secret，再点连接', 'info')
      return
    }
    setBusy(true)
    try {
      const { url } = await api.communityAuthUrl()
      window.location.href = url
    } catch (e: any) {
      toast(`发起授权失败：${e.message || e}`, 'err')
      setBusy(false)
    }
  }

  const disconnect = async () => {
    setBusy(true)
    try {
      await api.communityDisconnect()
      toast('已断开 GitHub', 'ok')
      await reload()
    } catch (e: any) {
      toast(`断开失败：${e.message || e}`, 'err')
    } finally {
      setBusy(false)
    }
  }

  const saveConfig = async () => {
    setBusy(true)
    try {
      await api.saveCommunityConfig({
        client_id: form.client_id,
        client_secret: form.client_secret || undefined,
        repo: form.repo,
        branch: form.branch,
        dir: form.dir,
      })
      toast('GitHub 配置已保存', 'ok')
      setForm({ ...form, client_secret: '' })
      await reload()
    } catch (e: any) {
      toast(`保存失败：${e.message || e}`, 'err')
    } finally {
      setBusy(false)
    }
  }

  const connected = !!config?.connected

  return (
    <Modal
      title="GitHub 账户"
      subtitle="连上之后可以把画布发布成公共模板，也能一键加载别人分享的模板。"
      onClose={onClose}
      footer={
        <>
          <button onClick={onClose}>关闭</button>
          {connected ? (
            <button className="danger" onClick={disconnect} disabled={busy}>
              断开连接
            </button>
          ) : (
            <button className="primary" onClick={connect} disabled={busy}>
              {busy ? <span className="spin" /> : null} 连接 GitHub
            </button>
          )}
        </>
      }
    >
      <div className={`gh-account${connected ? ' on' : ''}`}>
        <div className="gh-avatar">{connected ? (config?.login || 'GH').slice(0, 1).toUpperCase() : '?'}</div>
        <div style={{ flex: 1, minWidth: 0 }}>
          {connected ? (
            <>
              <div className="gh-name">@{config?.login}</div>
              <div className="dim small">已连接，可以发布和加载公共模板</div>
            </>
          ) : (
            <>
              <div className="gh-name">未连接 GitHub</div>
              <div className="dim small">连接后才能发布模板、拉取社区模板</div>
            </>
          )}
        </div>
        <span className={`badge${connected ? ' ok' : ''}`}>{connected ? '已连接' : '未连接'}</span>
      </div>

      {connected && (
        <div className="hint-box">
          发布目标：<code className="mono">{config?.repo || '未设置仓库'}</code>
          {config?.branch ? ` · 分支 ${config.branch}` : ''}
          {config?.dir ? ` · 目录 ${config.dir}` : ''}
        </div>
      )}

      <div className="row" style={{ marginTop: 12 }}>
        <button className="ghost sm" onClick={() => setAdvanced((v) => !v)}>
          {advanced ? '收起' : '展开'} OAuth / 仓库设置
        </button>
        {!connected && config && !config.configured && (
          <span className="dim small">还没配 OAuth 应用，先展开填一下</span>
        )}
      </div>

      {advanced && (
        <div style={{ marginTop: 10 }}>
          <label className="field">
            <span>OAuth Client ID</span>
            <input
              value={form.client_id}
              placeholder="GitHub OAuth App 的 Client ID"
              onChange={(e) => setForm({ ...form, client_id: e.target.value })}
            />
          </label>
          <label className="field">
            <span>OAuth Client Secret</span>
            <input
              type="password"
              value={form.client_secret}
              placeholder={config?.client_secret_mask ? `已保存 ${config.client_secret_mask}（留空不改）` : 'GitHub OAuth App 的 Client Secret'}
              onChange={(e) => setForm({ ...form, client_secret: e.target.value })}
            />
          </label>
          <label className="field">
            <span>模板仓库</span>
            <input
              value={form.repo}
              placeholder="owner/repo，例如 YT-Proteus-bot/agent-templates"
              onChange={(e) => setForm({ ...form, repo: e.target.value })}
            />
          </label>
          <div className="row" style={{ gap: 8 }}>
            <label className="field" style={{ flex: 1 }}>
              <span>分支</span>
              <input value={form.branch} onChange={(e) => setForm({ ...form, branch: e.target.value })} />
            </label>
            <label className="field" style={{ flex: 1 }}>
              <span>目录</span>
              <input value={form.dir} onChange={(e) => setForm({ ...form, dir: e.target.value })} />
            </label>
          </div>
          <div className="hint-box">
            回调地址填：<code className="mono">{config?.callback_url || '/'}</code>
            <br />
            secret 会加密存在本地库，不会随模板上传。
          </div>
          <button className="sm primary" onClick={saveConfig} disabled={busy}>
            保存设置
          </button>
        </div>
      )}
    </Modal>
  )
}
