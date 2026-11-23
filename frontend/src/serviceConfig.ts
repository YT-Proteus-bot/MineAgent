import { DEFAULT_SERVICE, type ServiceConfig } from './types'

/** 画布 service 配置的合并与文本化工具：服务面板与数据中台共用。 */
export function mergeService(raw: any): ServiceConfig {
  return {
    entry: { ...DEFAULT_SERVICE.entry, ...(raw?.entry || {}) },
    session: { ...DEFAULT_SERVICE.session, ...(raw?.session || {}) },
    runtime: { ...DEFAULT_SERVICE.runtime, ...(raw?.runtime || {}) },
    observability: { ...DEFAULT_SERVICE.observability, ...(raw?.observability || {}) },
    security: { ...DEFAULT_SERVICE.security, ...(raw?.security || {}) },
    data: { ...DEFAULT_SERVICE.data, ...(raw?.data || {}) },
    eval: { ...DEFAULT_SERVICE.eval, ...(raw?.eval || {}) },
  }
}

export function datasetsText(list: { logical: string; physical: string; mode: string }[]): string {
  return (list || [])
    .map((d) => `${d.logical} = ${d.physical}${d.mode === 'write' ? ':write' : ''}`)
    .join('\n')
}

export function parseDatasets(text: string) {
  return text
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith('#'))
    .map((line) => {
      const idx = line.indexOf('=')
      const logical = (idx >= 0 ? line.slice(0, idx) : line).trim()
      let physical = (idx >= 0 ? line.slice(idx + 1) : '').trim()
      let mode = 'read'
      if (physical.endsWith(':write')) {
        mode = 'write'
        physical = physical.slice(0, -6).trim()
      }
      return { logical, physical, mode }
    })
    .filter((d) => d.logical)
}
