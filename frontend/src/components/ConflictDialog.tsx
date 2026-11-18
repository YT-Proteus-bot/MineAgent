import Modal from './Modal'

/**
 * 同步冲突对话框：不自动合并，只让用户明确选一次。
 *
 * 两种场景：
 * - remote-changed：推送时远端已经变了
 * - local-changed：拉取时本地有没同步的修改
 */
export type ConflictInfo = {
  kind: 'remote-changed' | 'local-changed'
  message?: string
  canvas_id?: string
  canvas_name?: string
  remote_slug?: string
  base_rev?: number
  local_rev?: number
  remote_rev?: number
  remote_updated_at?: string
  remote_author?: string
}

export type ConflictChoice = 'overwrite' | 'save-as-new' | 'cancel' | 'pull-first'

export default function ConflictDialog({
  info,
  busy,
  onChoose,
  onClose,
}: {
  info: ConflictInfo
  busy?: boolean
  onChoose: (choice: ConflictChoice) => void
  onClose: () => void
}) {
  const isPush = info.kind === 'remote-changed'

  return (
    <Modal
      title={isPush ? '远端模板已经更新' : '本地有未同步的修改'}
      subtitle={
        isPush
          ? '你上次同步之后，别人（或你从别处）改过这个模板。直接推会把对方的改动覆盖掉。'
          : '这张画布在本地改过，但还没推回远端。直接拉取会丢掉这些修改。'
      }
      onClose={onClose}
      footer={
        <>
          <button onClick={() => onChoose('cancel')} disabled={busy}>
            取消
          </button>
          {isPush ? (
            <button className="danger" onClick={() => onChoose('overwrite')} disabled={busy}>
              仍然覆盖推送
            </button>
          ) : (
            <button className="danger" onClick={() => onChoose('overwrite')} disabled={busy}>
              覆盖本地
            </button>
          )}
        </>
      }
    >
      <div className="conflict-detail">
        {isPush ? (
          <>
            <div className="row">
              <span className="dim">远端版本</span>
              <span className="mono">
                第 {info.remote_rev ?? '?'} 版
                {info.remote_updated_at ? ` · ${info.remote_updated_at.slice(0, 16).replace('T', ' ')}` : ''}
              </span>
            </div>
            <div className="row">
              <span className="dim">你上次同步</span>
              <span className="mono">第 {info.base_rev ?? '?'} 版</span>
            </div>
            {info.remote_author && (
              <div className="row">
                <span className="dim">远端作者</span>
                <span className="mono">@{info.remote_author}</span>
              </div>
            )}
          </>
        ) : (
          <>
            <div className="row">
              <span className="dim">画布</span>
              <span className="mono">{info.canvas_name || info.canvas_id}</span>
            </div>
            <div className="row">
              <span className="dim">本地版本</span>
              <span className="mono">第 {info.local_rev ?? '?'} 版</span>
            </div>
          </>
        )}
      </div>

      <div className="hint-box">
        {isPush
          ? '建议先拉取远端最新版，在画布上合并完自己的改动再推送。'
          : '想保住本地改动的话，可以先「另存为新画布」，再拉取远端版本。'}
      </div>

      {isPush ? (
        <button
          className="ghost sm"
          onClick={() => onChoose('pull-first')}
          disabled={busy}
          style={{ marginTop: 8 }}
        >
          先拉取远端，我自己合并
        </button>
      ) : (
        <button
          className="ghost sm"
          onClick={() => onChoose('save-as-new')}
          disabled={busy}
          style={{ marginTop: 8 }}
        >
          保留本地修改，另存为新画布
        </button>
      )}
    </Modal>
  )
}
