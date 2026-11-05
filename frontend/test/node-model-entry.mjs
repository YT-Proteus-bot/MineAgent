import puppeteer from 'puppeteer-core'
import path from 'node:path'
import os from 'node:os'
import fs from 'node:fs'

const BASE = 'http://127.0.0.1:8000'
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const SHOTS = path.join(os.tmpdir(), 'mineagent-node-model')
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
await sleep(1600)

const openMenuFor = async (kind) => {
  await page.evaluate((k) => {
    const el = [...document.querySelectorAll('.agent-node')].find(
      (n) => n.querySelector('.node-kind')?.textContent === k,
    )
    el?.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, clientX: 700, clientY: 500 }))
  }, kind)
  await page.waitForSelector('.ctx-menu', { timeout: 6000 })
  await sleep(300)
  return page.$$eval('.ctx-menu .ctx-item', (els) => els.map((e) => e.textContent.trim()))
}

console.log('\n[A] agent 节点有「配置模型」')
const agentItems = await openMenuFor('agent')
check('agent 节点可配模型', agentItems.some((t) => t.includes('配置模型')), agentItems.join(' | '))
await page.keyboard.press('Escape')
await sleep(300)

console.log('\n[B] 会调 llm 的非 agent 节点也能配')
for (const kind of ['planner', 'observation', 'formatter']) {
  const items = await openMenuFor(kind)
  check(`${kind} 节点可配模型`, items.some((t) => t.includes('配置模型')))
  await page.keyboard.press('Escape')
  await sleep(250)
}
await page.screenshot({ path: path.join(SHOTS, '01-menu.png') })

console.log('\n[C] 不调 llm 的节点不显示该项')
const toolItems = await openMenuFor('tool')
check('tool 节点不显示配置模型', !toolItems.some((t) => t.includes('配置模型')), toolItems.join(' | '))
await page.keyboard.press('Escape')
await sleep(300)

check('无 JS 运行时错误', errors.length === 0, errors.slice(0, 2).join(' ;; '))

await browser.close()
console.log(`\n${fail === 0 ? '全部通过 ✅' : `${fail} 项失败 ❌`}   截图：${SHOTS}`)
await sleep(200)
process.exitCode = fail === 0 ? 0 : 1
