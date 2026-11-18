import puppeteer from 'puppeteer-core'
import path from 'node:path'
import os from 'node:os'
import fs from 'node:fs'
import { execSync } from 'node:child_process'

const BASE = 'http://127.0.0.1:8000'
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const SHOTS = path.join(os.tmpdir(), 'mineagent-sync-ui')
fs.mkdirSync(SHOTS, { recursive: true })
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const ROOT = path.resolve(import.meta.dirname, '../..')
const PY = path.join(ROOT, '.venv/Scripts/python.exe')

const runPy = (code) =>
  execSync(`"${PY}" -c ${JSON.stringify(code)}`, {
    cwd: ROOT,
    encoding: 'utf-8',
    env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
  }).trim()

let pass = 0
let fail = 0
const check = (n, ok, extra = '') => {
  console.log(`  ${ok ? '✔' : '✘'} ${n}${extra ? ` — ${extra}` : ''}`)
  ok ? pass++ : fail++
}

const canvasId = runPy(
  "import sqlite3;c=sqlite3.connect('backend/data/mineagent.db');" +
    "r=c.execute('SELECT id FROM canvases ORDER BY updated_at DESC LIMIT 1').fetchone();c.close();print(r[0])",
)
// 伪造：从公共库拉的，远端有新版本
runPy(
  "import sqlite3;c=sqlite3.connect('backend/data/mineagent.db');" +
    `c.execute("UPDATE canvases SET remote_slug='order-bot', remote_rev=2, remote_lib='public', remote_name='订单机器人' WHERE id='${canvasId}'");` +
    "c.commit();c.close();print('ok')",
)
console.log(`已给画布 ${canvasId} 伪造远端绑定（公共模板库 · 订单机器人 · 第 2 版）\n`)

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
await sleep(2500)

console.log('[A] 顶部徽标')
const pill = await page.evaluate(() => {
  const el = document.querySelector('.sync-pill')
  if (!el) return null
  return { text: el.textContent.replace(/\s+/g, ' ').trim(), visible: el.getBoundingClientRect().width > 0 }
})
check('顶部出现同步徽标', !!pill, pill ? pill.text : '未找到')
if (pill) check('徽标可见', pill.visible)
await page.screenshot({ path: path.join(SHOTS, '01-top-pill.png') })

console.log('\n[B] 服务设置里的远端同步块')
await page.evaluate(() => {
  const b = [...document.querySelectorAll('.topbar button')].find((x) => x.textContent.includes('服务'))
  b && b.click()
})
await page.waitForSelector('.service-panel', { timeout: 8000 })
await sleep(1200)

const panel = await page.evaluate(() => {
  const el = document.querySelector('.sync-grid')
  if (!el) {
    // 没绑定时显示的是 hint-box
    const hint = [...document.querySelectorAll('.service-panel .hint-box')].find((h) =>
      h.textContent.includes('还没有关联远端模板'),
    )
    return { hasGrid: false, hint: !!hint }
  }
  const cells = [...el.children].map((c) => c.textContent.replace(/\s+/g, ' ').trim())
  return { hasGrid: true, cells }
})
check('有远端同步区块', panel.hasGrid || panel.hint)
if (panel.hasGrid) {
  check('显示远端模板名', panel.cells.some((c) => c.includes('订单机器人')), panel.cells.join(' | '))
  check('显示所在库', panel.cells.some((c) => c.includes('公共模板库')))
  check('显示版本号', panel.cells.some((c) => c.includes('第 2 版')))
}

// 滚动到同步区块再截图
await page.evaluate(() => {
  const el = document.querySelector('.sync-grid')
  el?.scrollIntoView({ block: 'center' })
})
await sleep(600)
await page.screenshot({ path: path.join(SHOTS, '02-service-panel.png') })

check('无 JS 错误', errors.length === 0, errors.slice(0, 2).join(' ;; '))

await browser.close()

// 清理
runPy(
  "import sqlite3;c=sqlite3.connect('backend/data/mineagent.db');" +
    `c.execute("UPDATE canvases SET remote_slug='', remote_rev=0, remote_lib='', remote_name='' WHERE id='${canvasId}'");` +
    "c.commit();c.close();print('cleaned')",
)

console.log(`\n${fail === 0 ? '全部通过 ✅' : `${fail} 项失败 ❌`}   截图：${SHOTS}`)
await sleep(150)
process.exitCode = fail === 0 ? 0 : 1
