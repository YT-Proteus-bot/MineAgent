import puppeteer from 'puppeteer-core'
import path from 'node:path'
import os from 'node:os'
import fs from 'node:fs'
import { execSync } from 'node:child_process'

const BASE = 'http://127.0.0.1:8000'
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const SHOTS = path.join(os.tmpdir(), 'mineagent-lib-label')
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

// 取两张画布：一张伪造公共库绑定，一张伪造私人库绑定
const ids = runPy(
  "import sqlite3;" +
    "c=sqlite3.connect('backend/data/mineagent.db');" +
    "rows=c.execute('SELECT id FROM canvases ORDER BY updated_at DESC LIMIT 2').fetchall();" +
    "c.close();print(','.join(r[0] for r in rows))",
).split(',')

if (ids.length < 2) {
  console.log('画布不足，跳过')
  process.exit(0)
}

// 公共库 + 远端有新版本
runPy(
  "import sqlite3;" +
    "c=sqlite3.connect('backend/data/mineagent.db');" +
    `c.execute("UPDATE canvases SET remote_slug='order-bot', remote_rev=2, remote_lib='public', remote_name='订单机器人' WHERE id='${ids[0]}'");` +
    "c.commit();c.close();print('ok')",
)
// 私人库
runPy(
  "import sqlite3;" +
    "c=sqlite3.connect('backend/data/mineagent.db');" +
    `c.execute("UPDATE canvases SET remote_slug='kb-qa', remote_rev=1, remote_lib='private:YT-Proteus-bot/MineAgent-Templates', remote_name='知识库问答' WHERE id='${ids[1]}'");` +
    "c.commit();c.close();print('ok')",
)
console.log('已伪造：公共库绑定 + 私人库绑定')

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

await page.evaluate(() => {
  const b = [...document.querySelectorAll('.topbar button')].find((x) =>
    x.textContent.includes('选择画布') || x.querySelector('.dim.small'),
  )
  b && b.click()
})
await sleep(900)

const items = await page.evaluate(() =>
  [...document.querySelectorAll('.menu-scroll .menu-item')]
    .slice(0, 4)
    .map((e) => e.textContent.replace(/\s+/g, ' ').trim()),
)
console.log('\n下拉前几项：')
items.forEach((t) => console.log('  ' + t))

await page.screenshot({ path: path.join(SHOTS, '01-lib-label.png') })
console.log(`\nJS 错误: ${errors.length}`)
await browser.close()

// 恢复
runPy(
  "import sqlite3;" +
    "c=sqlite3.connect('backend/data/mineagent.db');" +
    `c.execute("UPDATE canvases SET remote_slug='', remote_rev=0, remote_lib='', remote_name='' WHERE id IN ('${ids[0]}','${ids[1]}')");` +
    "c.commit();c.close();print('cleaned')",
)
console.log('已清理伪造数据')
console.log(`截图：${SHOTS}`)
