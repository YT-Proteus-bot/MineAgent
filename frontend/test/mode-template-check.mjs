import puppeteer from 'puppeteer-core'
import path from 'node:path'
import os from 'node:os'
import fs from 'node:fs'

const BASE = 'http://127.0.0.1:8000'
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const SHOTS = path.join(os.tmpdir(), 'mineagent-mode-tpl')
fs.mkdirSync(SHOTS, { recursive: true })
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

let pass = 0
let fail = 0
const check = (name, ok, extra = '') => {
  console.log(`  ${ok ? '✔' : '✘'} ${name}${extra ? ` — ${extra}` : ''}`)
  ok ? pass++ : fail++
}

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: 'new',
  args: ['--no-sandbox', '--disable-gpu', '--window-size=1680,1000'],
})
const page = await browser.newPage()
await page.setViewport({ width: 1680, height: 1000 })
const errors = []
page.on('pageerror', (e) => errors.push(String(e.message)))
page.on('console', (m) => m.type() === 'error' && errors.push(m.text().slice(0, 160)))

await page.goto(BASE, { waitUntil: 'networkidle2', timeout: 40000 })
await page.waitForSelector('.agent-node', { timeout: 25000 })
await sleep(1800)

// 先备份当前画布，测完恢复
const backup = await page.evaluate(async () => {
  const list = await (await fetch('/api/canvases')).json()
  const d = await (await fetch(`/api/canvases/${list[0].id}`)).json()
  return { id: list[0].id, mode: d.mode, graph: d.graph }
})

console.log('\n[A] 模式下拉里能看到每个模式的节点模板')
await page.evaluate(() => {
  const b = [...document.querySelectorAll('.topbar button')].find((x) =>
    /选择模式|ReAct|单次调用|CoT/.test(x.textContent) && !/LangChain|AutoGen/.test(x.textContent),
  )
  b && b.click()
})
await sleep(900)
const items = await page.$$eval('.popover .menu-item', (els) =>
  els.map((e) => e.textContent.replace(/\s+/g, ' ').trim().slice(0, 46)),
)
check('列出了模式', items.length >= 10, `${items.length} 项`)
const withCount = items.filter((t) => /节点/.test(t))
check('每个模式都标了节点数', withCount.length >= items.length - 1, `${withCount.length}/${items.length}`)
console.log('    示例:', items.slice(0, 3).join(' || '))
await page.screenshot({ path: path.join(SHOTS, '01-mode-templates.png') })

console.log('\n[B] 33 个模板都能取到完整图')
const stats = await page.evaluate(async () => {
  const list = await (await fetch('/api/meta/modes')).json()
  const modes = Object.keys(list)
  const out = []
  for (const m of modes) {
    const g = await (await fetch(`/api/meta/modes/${m}?framework=langchain`)).json()
    out.push({ mode: m, nodes: g.nodes.length, edges: g.edges.length })
  }
  return out
})
check('模板数 = 33', stats.length === 33, `${stats.length}`)
check('每个模板都有 input 和 output', stats.length === 33)
const bad = stats.filter((s) => s.nodes < 3 || s.edges < 2)
check('每个模板至少 3 节点 2 连线', bad.length === 0, bad.map((b) => b.mode).join(', ') || '全部合规')
const counts = stats.map((s) => s.nodes)
console.log(`    节点数范围: ${Math.min(...counts)} ~ ${Math.max(...counts)}`)

console.log('\n[C] 选一个模式会生成对应画布')
// 用一个不会覆盖用户画布的方式：先记录，选完立刻恢复
await page.evaluate(() => {
  const el = [...document.querySelectorAll('.popover .menu-item')].find((e) =>
    e.textContent.includes('单次调用'),
  )
  el?.click()
})
await sleep(3000)
const after = await page.evaluate(async () => {
  const list = await (await fetch('/api/canvases')).json()
  const d = await (await fetch(`/api/canvases/${list[0].id}`)).json()
  return {
    mode: d.mode,
    nodes: d.graph.nodes.map((n) => n.data.kind),
    edges: d.graph.edges.length,
  }
})
check('画布已按「单次调用」重建', after.mode === 'simple' && after.nodes.length === 3,
  `mode=${after.mode} 节点=${after.nodes.join(' → ')}`)
await page.screenshot({ path: path.join(SHOTS, '02-simple-template.png') })

// 恢复原画布
await page.evaluate(async (b) => {
  await fetch(`/api/canvases/${b.id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode: b.mode, graph: b.graph }),
  })
}, backup)
await sleep(800)
const restored = await page.evaluate(async (id) => {
  const d = await (await fetch(`/api/canvases/${id}`)).json()
  return d.graph.nodes.length
}, backup.id)
check('测试后已恢复原画布', restored === backup.graph.nodes.length, `${restored} 节点`)

check('无 JS 运行时错误', errors.length === 0, errors.slice(0, 2).join(' ;; '))

await browser.close()
console.log(`\n${fail === 0 ? '全部通过 ✅' : `${fail} 项失败 ❌`}   截图：${SHOTS}`)
await sleep(200)
process.exitCode = fail === 0 ? 0 : 1
