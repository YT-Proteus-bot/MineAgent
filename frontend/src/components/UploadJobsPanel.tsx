import { useStore } from '../store'

/** 后台上传任务面板：上传弹窗关闭后，进度和结果都在这里看。 */
export default function UploadJobsPanel() {
  const jobs = useStore((s) => s.uploadJobs)
  const clearFinished = useStore((s) => s.clearFinishedUploads)

  if (jobs.length === 0) return null
  const running = jobs.filter((j) => j.status === 'running').length
  const finished = jobs.length - running

  return (
    <div className="upload-jobs">
      <div className="upload-jobs-head">
        <span>上传任务{running > 0 ? `（${running} 个进行中）` : ''}</span>
        {finished > 0 && (
          <button className="sm" onClick={clearFinished}>
            清除已完成
          </button>
        )}
      </div>
      <div className="upload-jobs-list">
        {jobs.map((j) => (
          <div key={j.id} className={`upload-job ${j.status}`}>
            <div className="row" style={{ gap: 6 }}>
              <span className="upload-job-name">{j.name}</span>
              <div style={{ flex: 1 }} />
              {j.status === 'running' && <span className="spin" style={{ width: 12, height: 12 }} />}
              {j.status === 'ok' && <span style={{ color: 'var(--ok)' }}>✓</span>}
              {j.status === 'error' && <span style={{ color: 'var(--err)' }}>⚠</span>}
            </div>
            {j.status === 'ok' && j.prUrl && (
              <a href={j.prUrl} target="_blank" rel="noreferrer" className="small">
                {j.prUrl}
              </a>
            )}
            {j.status === 'error' && (
              <div className="dim small" style={{ color: 'var(--err)', marginTop: 3 }}>
                {j.error}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
