import puppeteer from 'puppeteer-core'
import path from 'node:path'
import os from 'node:os'
import fs from 'node:fs'

const BASE = 'http://127.0.0.1:8000'
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const SHOTS = path.join(os.tmpdir(), 'mineagent-tools')
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

// 找一个已有的 tool 节点，右键看预设
const opened = await page.evaluate(() => {
  const el = [...document.querySelectorAll('.agent-node')].find(
    (n) => n.querySelector('.node-kind')?.textContent?.trim() === 'tool',
  )
  if (!el) return false
  const r = el.getBoundingClientRect()
  el.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, clientX: r.x + 20, clientY: r.y + 20 }))
  return true
})

if (!opened) {
  console.log('当前画布没有 tool 节点，跳过 UI 检查')
} else {
  await page.waitForSelector('.ctx-menu', { timeout: 6000 })
  await sleep(600)
  const items = await page.$$eval('.ctx-menu .ctx-item', (els) =>
    els.map((e) => e.textContent.replace(/\s+/g, ' ').trim()),
  )
  const hasPreset = items.some((t) => t.includes('预设') || t.includes('工具'))
  console.log('tool 右键菜单项:', items.slice(0, 6).join(' | '))
  console.log(`  ${hasPreset ? '✔' : '✘'} 有工具预设入口`)
  await page.screenshot({ path: path.join(SHOTS, '01-tool-menu.png') })
  await page.keyboard.press('Escape')
}

// 再确认 meta 里工具数
const count = await page.evaluate(async () => {
  const meta = await (await fetch('/api/meta')).json()
  return {
    total: (meta.tool_presets || []).length,
    sample: (meta.tool_presets || []).slice(0, 5).map((t) => t.label),
  }
})
console.log(`\n工具预设总数: ${count.total}`)
console.log(`前几个: ${count.sample.join(' / ')}`)
console.log(`JS 错误: ${errors.length}`)
await browser.close()
