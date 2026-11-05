import { useRef, useState } from 'react'
import { useStore } from '../store'
import { DEFAULT_BACKGROUND } from '../types'

const SWATCHES = [
  { value: '', label: '透明' },
  { value: '#0a0d14', label: '深空' },
  { value: '#0f172a', label: '夜蓝' },
  { value: '#111827', label: '石墨' },
  { value: '#1e1b4b', label: '靛紫' },
  { value: '#0b1f1a', label: '墨绿' },
  { value: '#1a1215', label: '酒红' },
  { value: '#f8fafc', label: '纸白' },
  { value: '#f1f5f9', label: '雾白' },
  { value: '#e0e7ff', label: '淡蓝' },
  { value: '#fef3c7', label: '米黄' },
]

const FITS: { value: 'cover' | 'contain' | 'repeat' | 'center'; label: string }[] = [
  { value: 'cover', label: '铺满' },
  { value: 'contain', label: '适应' },
  { value: 'repeat', label: '平铺' },
  { value: 'center', label: '居中' },
]

export default function BackgroundPanel({ onClose }: { onClose: () => void }) {
  const canvas = useStore((s) => s.canvas)
  const setBackground = useStore((s) => s.setBackground)
  const uploadBackground = useStore((s) => s.uploadBackground)
  const removeBackgroundImage = useStore((s) => s.removeBackgroundImage)
  const fileRef = useRef<HTMLInputElement>(null)
  const [uploading, setUploading] = useState(false)

  const bg = { ...DEFAULT_BACKGROUND, ...(canvas?.background || {}) }
  const hasImage = !!bg.image

  const pickFile = async (file: File | null | undefined) => {
    if (!file) return
    setUploading(true)
    try {
      await uploadBackground(file)
    } finally {
      setUploading(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  return (
    <div className="bg-panel">
      <div className="bg-panel-head">
        <span>画布背景</span>
        <button className="ghost icon" onClick={onClose} title="关闭">
          ✕
        </button>
      </div>

      <div className="bg-panel-body">
        <div className="bg-section-title">底色</div>
        <div className="bg-swatches">
          {SWATCHES.map((s) => (
            <button
              key={s.label}
              className={`bg-swatch${bg.color === s.value ? ' active' : ''}${
                s.value === '' ? ' transparent' : ''
              }`}
              style={s.value ? { background: s.value } : undefined}
              title={s.label}
              onClick={() => setBackground({ color: s.value })}
            >
              {s.value === '' ? '／' : ''}
            </button>
          ))}
        </div>
        <div className="row" style={{ marginTop: 8 }}>
          <input
            type="color"
            value={bg.color || '#0a0d14'}
            onChange={(e) => setBackground({ color: e.target.value })}
            className="bg-color-input"
            title="自定义颜色"
          />
          <span className="dim small">
            {bg.color ? `自定义 ${bg.color.toUpperCase()}` : '当前透明（露出页面底色）'}
          </span>
          <div style={{ flex: 1 }} />
          {bg.color && (
            <button className="sm" onClick={() => setBackground({ color: '' })}>
              恢复透明
            </button>
          )}
        </div>

        <div className="bg-section-title" style={{ marginTop: 16 }}>
          背景图片
        </div>
        <input
          ref={fileRef}
          type="file"
          accept="image/png,image/jpeg,image/webp,image/gif,image/bmp"
          style={{ display: 'none' }}
          onChange={(e) => pickFile(e.target.files?.[0])}
        />
        <div className="row">
          <button className="sm" onClick={() => fileRef.current?.click()} disabled={uploading}>
            {uploading ? <span className="spin" /> : '⇪'} {hasImage ? '换个图片' : '上传图片'}
          </button>
          {hasImage && (
            <>
              <button className="sm danger" onClick={() => removeBackgroundImage()}>
                移除
              </button>
              <span className="dim small">PNG / JPG / WebP / GIF，≤ 12MB</span>
            </>
          )}
          {!hasImage && <span className="dim small">PNG / JPG / WebP / GIF，≤ 12MB</span>}
        </div>

        {hasImage && (
          <>
            <div className="bg-preview">
              <div
                className="bg-preview-img"
                style={{ backgroundImage: `url(/api/backgrounds/${bg.image})` }}
              />
              <span className="dim small mono" title={bg.image}>
                {bg.image}
              </span>
            </div>
            <div className="bg-section-title" style={{ marginTop: 10 }}>
              填充方式
            </div>
            <div className="bg-seg">
              {FITS.map((f) => (
                <button
                  key={f.value}
                  className={`bg-seg-btn${bg.image_fit === f.value ? ' active' : ''}`}
                  onClick={() => setBackground({ image_fit: f.value })}
                >
                  {f.label}
                </button>
              ))}
            </div>
            <label className="field" style={{ marginTop: 10 }}>
              <span>图片透明度 {Math.round(bg.image_opacity * 100)}%</span>
              <input
                type="range"
                min={0.05}
                max={1}
                step={0.05}
                value={bg.image_opacity}
                onChange={(e) => setBackground({ image_opacity: Number(e.target.value) })}
              />
            </label>
          </>
        )}

        <div className="bg-section-title" style={{ marginTop: 16 }}>
          点阵网格
        </div>
        <div className="row">
          <label className="row" style={{ gap: 7 }}>
            <input
              type="checkbox"
              checked={bg.grid}
              onChange={(e) => setBackground({ grid: e.target.checked })}
              style={{ width: 15, height: 15 }}
            />
            <span className="small">显示网格（编辑时对齐用）</span>
          </label>
          <div style={{ flex: 1 }} />
          <input
            type="color"
            value={bg.grid_color}
            onChange={(e) => setBackground({ grid_color: e.target.value })}
            className="bg-color-input"
            title="网格颜色"
            disabled={!bg.grid}
          />
        </div>

        <div className="hint-box" style={{ marginTop: 14 }}>
          背景属于显示设置，改完立即生效并保存，不占用「未保存」标记；
          背景图存在本机 <code className="mono">backend/data/backgrounds/</code>，不会进 git。
        </div>
      </div>
    </div>
  )
}
