import puppeteer from 'puppeteer-core'
import path from 'node:path'
import os from 'node:os'
import fs from 'node:fs'
import { execSync } from 'node:child_process'

const BASE = 'http://127.0.0.1:8000'
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const SHOTS = path.join(os.tmpdir(), 'mineagent-sync-badge')
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

// 挑一张画布，伪造"从 demo-template 第 2 版拉来"
let canvasId = ''
try {
  // 命令行传多行 Python 会被转义破坏，这里压成单行
  canvasId = runPy(
    "import sqlite3,pathlib;" +
      "c=sqlite3.connect('backend/data/mineagent.db');" +
      "r=c.execute('SELECT id FROM canvases ORDER BY updated_at DESC LIMIT 1').fetchone();" +
      "c.close();print(r[0])",
  )
} catch (e) {
  console.log('取画布失败', e.message)
}

if (canvasId) {
  try {
    runPy(
      "import sqlite3;" +
        "c=sqlite3.connect('backend/data/mineagent.db');" +
        `c.execute("UPDATE canvases SET remote_slug='demo-template', remote_rev=2, ` +
        `remote_lib='public', remote_name='演示模板' WHERE id='${canvasId}'");` +
        "c.commit();c.close();print('ok')",
    )
    console.log(`已给画布 ${canvasId} 伪造绑定信息`)
  } catch (e) {
    console.log('伪造失败', e.message)
  }
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

await page.goto(BASE, { waitUntil: 'networkidle2', timeout: 40000 })
await page.waitForSelector('.agent-node', { timeout: 25000 })
await sleep(2500)

// 打开画布下拉
await page.evaluate(() => {
  const b = [...document.querySelectorAll('.topbar button')].find((x) =>
    x.textContent.includes('选择画布') || x.querySelector('.dim.small'),
  )
  b && b.click()
})
await sleep(900)

const menuText = await page.evaluate(() => {
  const items = [...document.querySelectorAll('.popover .menu-item')]
  return items.slice(0, 6).map((e) => e.textContent.replace(/\s+/g, ' ').trim())
})
console.log('\n画布下拉前几项:')
menuText.forEach((t) => console.log('  ' + t))

await page.screenshot({ path: path.join(SHOTS, '01-canvas-dropdown.png') })
console.log(`\nJS 错误: ${errors.length}`)
await browser.close()

// 清理伪造数据
if (canvasId) {
  try {
    runPy(
      "import sqlite3;" +
        "c=sqlite3.connect('backend/data/mineagent.db');" +
        `c.execute("UPDATE canvases SET remote_slug='', remote_rev=0, remote_lib='', remote_name='' WHERE id='${canvasId}'");` +
        "c.commit();c.close();print('cleaned')",
    )
    console.log('已清理伪造的绑定信息')
  } catch (e) {
    console.log('清理失败（可手动忽略）', e.message)
  }
}
console.log(`截图：${SHOTS}`)
