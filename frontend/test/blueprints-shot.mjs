import puppeteer from 'puppeteer-core'
import path from 'node:path'
import os from 'node:os'
import fs from 'node:fs'

const BASE = 'http://127.0.0.1:8000'
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const SHOTS = path.join(os.tmpdir(), 'mineagent-blueprints')
fs.mkdirSync(SHOTS, { recursive: true })
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: 'new',
  args: ['--no-sandbox', '--disable-gpu', '--window-size=1680,1000'],
})
const page = await browser.newPage()
await page.setViewport({ width: 1680, height: 1000 })
const errors = []
page.on('pageerror', (e) => errors.push(String(e.message)))

await page.goto(BASE, { waitUntil: 'networkidle2', timeout: 40000 })
await page.waitForSelector('.agent-node', { timeout: 25000 })
await sleep(1500)

// 拿到所有 蓝图画布
const list = await page.evaluate(async () => {
  const all = await (await fetch('/api/canvases')).json()
  return all
    .filter((c) => c.name.startsWith('开源 ·') || c.name.startsWith('闭源 ·'))
    .map((c) => ({ id: c.id, name: c.name }))
})
console.log(`找到 ${list.length} 张架构画布\n`)

const targets = [
  '开源 · LangGraph 状态图',
  '开源 · AutoGen 对话驱动',
  '闭源 · AWS Bedrock Agents',
  '闭源 · DeepSeek Super-agent',
]

for (const name of targets) {
  const item = list.find((c) => c.name === name)
  if (!item) continue
  // 直接通过接口切画布后刷新，避免依赖下拉菜单结构
  await page.evaluate(async (id) => {
    await fetch(`/api/canvases/${id}/load`, { method: 'POST' }).catch(() => {})
  }, item.id)
  await page.goto(`${BASE}/?canvas=${item.id}`, { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('.agent-node', { timeout: 20000 })
  await sleep(2000)

  const info = await page.evaluate(() => ({
    nodes: document.querySelectorAll('.agent-node').length,
    edges: document.querySelectorAll('.react-flow__edge').length,
    title: document.querySelector('.canvas-name, .topbar .name')?.textContent?.trim() || '',
  }))
  const file = path.join(SHOTS, `${name.replace(/[·\s]/g, '_')}.png`)
  await page.screenshot({ path: file })
  console.log(`  ${name.padEnd(28)} ${info.nodes} 节点 / ${info.edges} 连线  → ${path.basename(file)}`)
}

console.log(`\nJS 错误: ${errors.length}`)
await browser.close()
