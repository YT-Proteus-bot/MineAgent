import { useState } from 'react'

import { useStore } from '../store'
import { ProvidersPanel } from './ProvidersPanel'

/**
 * 数据中台：画布级数据层的唯一入口。
 *
 * 数据源（连接 + 密钥）从「画布配置」迁到这里，数据集与指标后续挂在同一个面板下，
 * 这样节点选数据、人配连接都在一个地方，不会出现两套配置各说各话。
 */
type Tab = 'sources' | 'datasets'

export default function DataHubModal({ onClose }: { onClose: () => void }) {
  const canvas = useStore((s) => s.canvas)
  const [tab, setTab] = useState<Tab>('sources')

  return (
    <div
      className="modal-mask"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <div
        className="modal"
        style={{
          width: 'min(1120px, 94vw)',
          height: 'min(780px, 88vh)',
          display: 'flex',
          flexDirection: 'column',
          paddingBottom: 0,
        }}
      >
        <div className="kb-head">
          <div className="kb-head-left">
            <button className="ghost sm" onClick={onClose} title="关闭">←</button>
            <span className="kb-title">数据中台</span>
            <span className="dim small">
              {canvas ? `当前画布：${canvas.name}` : '未打开画布'}
            </span>
          </div>
          <div className="kb-head-right">
            <div className="tabs">
              <div
                className={`tab${tab === 'sources' ? ' active' : ''}`}
                onClick={() => setTab('sources')}
                title="连接：业务库 / 文档库 / HTTP 接口（密钥只存密文）"
              >
                数据源
              </div>
              <div
                className={`tab${tab === 'datasets' ? ' active' : ''}`}
                onClick={() => setTab('datasets')}
                title="数据集：把数据源里的表或接口登记成节点可直接引用的名字"
              >
                数据集
              </div>
            </div>
          </div>
        </div>

        <div className="kb-body" style={{ flex: 1, overflow: 'auto' }}>
          {!canvas ? (
            <div className="kb-empty">先打开一张画布，再配置它的数据源。</div>
          ) : tab === 'sources' ? (
            <ProvidersPanel kind="data" canvasId={canvas.id} />
          ) : (
            <div className="kb-empty">
              数据集还没接入。下一步会把数据源里的表登记成「逻辑名 → 表 / SQL」，
              节点里就能用 <code className="mono">ctx.data.query("orders", status="paid")</code> 取数。
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
