import { useEffect, useState } from 'react'
import { api } from '../api'
import { useStore } from '../store'
import type { CommunityConfig, TemplateLib } from '../types'
import Modal from './Modal'

/**
 * GitHub 账户：连接 / 断开 / 查看当前登录身份，以及配置多个公共/私人模板仓库。
 * 登录走 OAuth 授权码流程，回调后回到首页并带 ?github=connected。
 */
export default function GitHubAccountModal({ onClose }: { onClose: () => void }) {
  const toast = useStore((s) => s.toast)
  const [config, setConfig] = useState<CommunityConfig | null>(null)
  const [busy, setBusy] = useState(false)
  const [advanced, setAdvanced] = useState(false)
  const [libs, setLibs] = useState<TemplateLib[]>([])
  const [form, setForm] = useState({
    client_id: '',
    client_secret: '',
    repo: '',
    branch: 'main',
    dir: 'templates',
  })

  const reload = async () => {
    try {
      const c = await api.communityConfig()
      setConfig(c)
      setForm((f) => ({
        ...f,
        client_id: f.client_id || c.client_id || '',
        repo: c.repo || '',
        branch: c.branch || 'main',
        dir: c.dir || 'templates',
      }))
      const res = await api.communityLibs()
      setLibs(res.libs || [])
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
      const res = await api.saveCommunityLibs(libs)
      setLibs(res.libs || [])
      toast('GitHub 配置与仓库已保存', 'ok')
      setForm({ ...form, client_secret: '' })
      await reload()
    } catch (e: any) {
      toast(`保存失败：${e.message || e}`, 'err')
    } finally {
      setBusy(false)
    }
  }

  const updateLib = (id: string, patch: Partial<TemplateLib>) =>
    setLibs((list) => list.map((l) => (l.id === id ? { ...l, ...patch } : l)))

  const connected = !!config?.connected

  return (
    <Modal
      title="GitHub 账户"
      subtitle="连上之后可以发布和加载模板；仓库在下面「仓库设置」里配置，支持多个公共库和私人库。"
      onClose={onClose}
      width={760}
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
        <div className="gh-avatar">
          {connected ? (config?.login || 'GH').slice(0, 1).toUpperCase() : '?'}
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          {connected ? (
            <>
              <div className="gh-name">@{config?.login}</div>
              <div className="dim small">已连接，可以发布和加载模板</div>
            </>
          ) : (
            <>
              <div className="gh-name">未连接 GitHub</div>
              <div className="dim small">连接后才能发布模板、拉取模板库</div>
            </>
          )}
        </div>
        <span className={`badge${connected ? ' ok' : ''}`}>{connected ? '已连接' : '未连接'}</span>
      </div>

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

          <div className="community-head" style={{ marginTop: 12 }}>
            <span>仓库设置（{libs.length}）</span>
            <span className="dim small">公共库走 PR；私人库直接提交到配置的分支</span>
            <div style={{ flex: 1 }} />
            <button
              className="sm"
              onClick={() =>
                setLibs([
                  ...libs,
                  {
                    id: `new-${Date.now()}`,
                    name: '',
                    kind: 'private',
                    repo: '',
                    branch: 'main',
                    dir: 'templates',
                  },
                ])
              }
            >
              + 添加仓库
            </button>
          </div>

          <div className="community-list" style={{ maxHeight: 240 }}>
            {libs.length === 0 && (
              <div className="dim" style={{ padding: '12px 0' }}>
                还没有仓库。添加一个公共或私人仓库，填上 owner/repo。
              </div>
            )}
            {libs.map((lib) => (
              <div key={lib.id} className="community-item" style={{ alignItems: 'flex-start' }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div className="row" style={{ gap: 8, marginBottom: 6, alignItems: 'flex-end' }}>
                    <label className="field" style={{ width: 130 }}>
                      <span>名称</span>
                      <input
                        className="mono"
                        value={lib.name}
                        placeholder="模板库名称"
                        onChange={(e) => updateLib(lib.id, { name: e.target.value })}
                      />
                    </label>
                    <label className="field" style={{ width: 100 }}>
                      <span>类型</span>
                      <select
                        value={lib.kind}
                        onChange={(e) =>
                          updateLib(lib.id, { kind: e.target.value as TemplateLib['kind'] })
                        }
                      >
                        <option value="public">公共</option>
                        <option value="private">私人</option>
                      </select>
                    </label>
                    <label className="field" style={{ flex: 1, minWidth: 220 }}>
                      <span>
                        仓库
                        {lib.visibility && (
                          <span
                            className={`badge${lib.visibility === 'private' ? ' warn' : ' ok'}`}
                            style={{ marginLeft: 6 }}
                          >
                            {lib.visibility === 'private' ? '私有' : '公开'}
                          </span>
                        )}
                      </span>
                      <input
                        className="mono"
                        value={lib.repo}
                        placeholder="owner/repo 或 https://github.com/owner/repo"
                        onChange={(e) => updateLib(lib.id, { repo: e.target.value })}
                      />
                    </label>
                  </div>
                  <div className="row" style={{ gap: 8, alignItems: 'flex-end' }}>
                    <label className="field" style={{ width: 120 }}>
                      <span>分支</span>
                      <input
                        className="mono"
                        value={lib.branch}
                        onChange={(e) => updateLib(lib.id, { branch: e.target.value })}
                      />
                    </label>
                    <label className="field" style={{ width: 140 }}>
                      <span>目录</span>
                      <input
                        className="mono"
                        value={lib.dir}
                        onChange={(e) => updateLib(lib.id, { dir: e.target.value })}
                      />
                    </label>
                  </div>
                </div>
                <button
                  className="sm"
                  onClick={() => setLibs((list) => list.filter((l) => l.id !== lib.id))}
                >
                  删除
                </button>
              </div>
            ))}
          </div>

          <div className="hint-box">
            回调地址填：<code className="mono">{config?.callback_url || '/'}</code>
            <br />
            secret 会加密存在本地库，不会随模板上传；私有仓库需要授权带 <code className="mono">repo</code> 权限。
          </div>
          <button className="sm primary" onClick={saveConfig} disabled={busy}>
            保存设置
          </button>
        </div>
      )}
    </Modal>
  )
}
