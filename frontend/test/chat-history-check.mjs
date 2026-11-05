import puppeteer from 'puppeteer-core'
import path from 'node:path'
import os from 'node:os'
import fs from 'node:fs'

const BASE = 'http://127.0.0.1:8000'
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const SHOTS = path.join(os.tmpdir(), 'mineagent-chat-history')
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

const msgCount = () => page.$$eval('.chat-msg', (els) => els.length)
const msgText = () =>
  page.$$eval('.chat-msg', (els) => els.map((e) => e.textContent.trim().slice(0, 20)))

console.log('\n[A] 打开面板会恢复最近的对话')
await page.waitForFunction(() => document.querySelectorAll('.chat-msg').length > 0, {
  timeout: 15000,
  polling: 300,
}).catch(() => {})
const restored = await msgCount()
check('恢复了上次的对话内容', restored > 0, `${restored} 条消息`)
await page.screenshot({ path: path.join(SHOTS, '01-restored.png') })

console.log('\n[B] 历史按钮列出所有对话')
await page.evaluate(() => {
  const b = [...document.querySelectorAll('.chat-head button')].find((e) =>
    e.textContent.includes('历史'),
  )
  b && b.click()
})
await sleep(700)
const items = await page.$$eval('.chat-history-item .ch-title', (els) =>
  els.map((e) => e.textContent.trim()),
).catch(() => [])
check('历史列表有内容', items.length >= 2, `${items.length} 段对话`)
console.log('    会话:', items.join(' | '))
await page.screenshot({ path: path.join(SHOTS, '02-history.png') })

console.log('\n[C] 新对话不会清掉历史')
const beforeCount = items.length
await page.evaluate(() => {
  const b = [...document.querySelectorAll('.chat-head button')].find((e) =>
    e.textContent.includes('新对话'),
  )
  b && b.click()
})
await sleep(600)
check('消息区已清空', (await msgCount()) === 0)
await page.evaluate(() => {
  const b = [...document.querySelectorAll('.chat-head button')].find((e) =>
    e.textContent.includes('历史'),
  )
  b && b.click()
})
await sleep(700)
const items2 = await page.$$eval('.chat-history-item .ch-title', (els) =>
  els.map((e) => e.textContent.trim()),
).catch(() => [])
check('历史仍然都在', items2.length === beforeCount, `${items2.length} / ${beforeCount}`)

console.log('\n[D] 点历史能切回去')
await page.evaluate(() => {
  const el = [...document.querySelectorAll('.chat-history-item')][1]
  el?.click()
})
await sleep(1200)
const back = await msgCount()
check('切换后加载了那段对话', back > 0, `${back} 条消息`)
const texts = await msgText()
console.log('    内容:', texts.join(' | '))
await page.screenshot({ path: path.join(SHOTS, '03-switched.png') })

check('无 JS 运行时错误', errors.length === 0, errors.slice(0, 2).join(' ;; '))

await browser.close()
console.log(`\n${fail === 0 ? '全部通过 ✅' : `${fail} 项失败 ❌`}   截图：${SHOTS}`)
await sleep(200)
process.exitCode = fail === 0 ? 0 : 1
