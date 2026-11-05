import puppeteer from 'puppeteer-core'
import path from 'node:path'
import os from 'node:os'
import fs from 'node:fs'

const BASE = 'http://127.0.0.1:8000'
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const SHOTS = path.join(os.tmpdir(), 'mineagent-effective')
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

await page.evaluate(() => {
  const b = [...document.querySelectorAll('.topbar button')].find(
    (x) => x.textContent.includes('模型') && !x.textContent.includes('用户'),
  )
  b && b.click()
})
await page.waitForSelector('.modal', { timeout: 6000 })
await sleep(1200)

const hint = await page.$eval('.modal .hint-box', (el) => el.textContent).catch(() => '')
console.log('  提示:', hint.replace(/\s+/g, ' ').slice(0, 120))
check('显示当前实际生效的模型', /实际生效/.test(hint))
check('显示来源（跟随用户中心）', /跟随「用户中心」|覆盖用户中心/.test(hint))
check('模型名不是空', !/未配置 @/.test(hint), hint.includes('deepseek') ? 'deepseek 系列' : '')
await page.screenshot({ path: path.join(SHOTS, '01-effective.png') })

check('无 JS 运行时错误', errors.length === 0, errors.slice(0, 2).join(' ;; '))
await browser.close()
console.log(`\n${fail === 0 ? '全部通过 ✅' : `${fail} 项失败 ❌`}   截图：${SHOTS}`)
await sleep(200)
process.exitCode = fail === 0 ? 0 : 1
