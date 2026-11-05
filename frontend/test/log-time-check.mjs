import puppeteer from 'puppeteer-core'
import path from 'node:path'
import os from 'node:os'
import fs from 'node:fs'

const BASE = 'http://127.0.0.1:8000'
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const SHOTS = path.join(os.tmpdir(), 'mineagent-log-time')
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

console.log('\n[A] 跑一次，看日志时间')
await page.evaluate(() => {
  const b = [...document.querySelectorAll('.topbar button')].find((e) =>
    e.textContent.includes('运行'),
  )
  b && b.click()
})
await sleep(800)
await page.evaluate(() => {
  const ta = [...document.querySelectorAll('textarea')].find((e) =>
    (e.getAttribute('placeholder') || '').includes('会传给 input'),
  )
  if (ta) {
    const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set
    setter.call(ta, '日志时间测试')
    ta.dispatchEvent(new Event('input', { bubbles: true }))
  }
})
await sleep(300)
await page.evaluate(() => {
  const b = [...document.querySelectorAll('button')].find((e) => e.textContent.includes('开始运行'))
  b && b.click()
})
await page
  .waitForFunction(() => document.querySelectorAll('.evt').length >= 3, {
    timeout: 60000,
    polling: 400,
  })
  .catch(() => {})
await sleep(2500)

const readTimes = () =>
  page.$$eval('.evt .time', (els) => els.map((e) => e.textContent.trim())).catch(() => [])

const t1 = await readTimes()
check('日志有内容', t1.length > 0, `${t1.length} 条`)
check('时间格式是 HH:MM:SS', t1.every((t) => /^\d{2}:\d{2}:\d{2}$/.test(t)), t1.slice(0, 3).join(', '))
check('不是占位符', !t1.includes('--:--:--'))

// 切个页签再切回来，触发重渲染；时间不应该跟着变
await sleep(2000)
await page.evaluate(() => {
  const b = [...document.querySelectorAll('.run-tabs button, .panel-tabs button')].find((e) =>
    e.textContent.includes('输出'),
  )
  b && b.click()
})
await sleep(600)
await page.evaluate(() => {
  const b = [...document.querySelectorAll('.run-tabs button, .panel-tabs button')].find((e) =>
    e.textContent.includes('过程'),
  )
  b && b.click()
})
await sleep(1500)
const t2 = await readTimes()
check('重渲染后时间不变（不是实时时钟）', JSON.stringify(t1) === JSON.stringify(t2), `${t1[0]} → ${t2[0]}`)

const monotonic = await page.evaluate(() => {
  const list = [...document.querySelectorAll('.evt .time')].map((e) => e.textContent.trim())
  return list.every((t, i) => i === 0 || list[i - 1] <= t)
})
check('时间按发生顺序递增', monotonic)
await page.screenshot({ path: path.join(SHOTS, '01-log-time.png') })

check('无 JS 运行时错误', errors.length === 0, errors.slice(0, 2).join(' ;; '))

await browser.close()
console.log(`\n${fail === 0 ? '全部通过 ✅' : `${fail} 项失败 ❌`}   截图：${SHOTS}`)
await sleep(200)
process.exitCode = fail === 0 ? 0 : 1
