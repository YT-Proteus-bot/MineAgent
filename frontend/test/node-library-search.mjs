import puppeteer from 'puppeteer-core'
import path from 'node:path'
import os from 'node:os'
import fs from 'node:fs'

const BASE = 'http://127.0.0.1:8000'
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const SHOTS = path.join(os.tmpdir(), 'mineagent-node-lib')
fs.mkdirSync(SHOTS, { recursive: true })
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

let pass = 0
let fail = 0
const check = (n, ok, extra = '') => {
  console.log(`  ${ok ? '✔' : '✘'} ${n}${extra ? ` — ${extra}` : ''}`)
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

await page.goto(BASE, { waitUntil: 'networkidle2', timeout: 40000 })
await page.waitForSelector('.agent-node', { timeout: 25000 })
await sleep(1500)

const openLibrary = async () => {
  const box = await page.evaluate(() => {
    const pane = document.querySelector('.react-flow__pane')
    const r = pane.getBoundingClientRect()
    return { x: r.x + 60, y: r.y + r.height - 120 }
  })
  await page.mouse.click(box.x, box.y, { button: 'right' })
  await page.waitForSelector('.ctx-menu', { timeout: 6000 })
  await sleep(400)
  await page.evaluate(() => {
    const el = [...document.querySelectorAll('.ctx-menu .ctx-item')].find((e) =>
      e.textContent.includes('添加节点'),
    )
    el && el.click()
  })
  await sleep(900)
}

const search = async (q) => {
  // 直接设值并派发 input 事件，确保 React 的 onChange 被触发
  const ok = await page.evaluate((value) => {
    const inp = document.querySelector('.ctx-search input, input[placeholder*="搜索节点"]')
    if (!inp) return false
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set
    setter.call(inp, value)
    inp.dispatchEvent(new Event('input', { bubbles: true }))
    inp.dispatchEvent(new Event('change', { bubbles: true }))
    return true
  }, q)
  if (!ok) return { inputFound: false, items: [] }
  await sleep(800)
  const items = await page.evaluate(() => {
    const menu = document.querySelector('.ctx-menu')
    if (!menu) return []
    return [...menu.querySelectorAll('*')]
      .filter((e) => e.children.length === 0 && e.textContent.trim())
      .map((e) => e.textContent.trim())
  })
  return { inputFound: true, items }
}

await openLibrary()

console.log('\n[A] 搜索 Router 相关')
const r1 = await search('Router')
check('能搜到主管 Supervisor（Router）', r1.items.some((t) => t.includes('Router')), r1.items.slice(0, 4).join(' | '))

const r2 = await search('主管')
check('用「主管」也能搜到', r2.items.some((t) => t.includes('主管')), r2.items.slice(0, 3).join(' | '))

console.log('\n[B] 搜索合并相关节点')
const m1 = await search('合并')
check('能搜到多路合并', m1.items.some((t) => t.includes('多路合并')), m1.items.slice(0, 4).join(' | '))

console.log('\n[C] 搜索 Supervisor 的 Worker 搭档')
const w1 = await search('Worker')
check('能搜到工作者 Worker', w1.items.some((t) => t.includes('Worker')), w1.items.slice(0, 3).join(' | '))

await page.screenshot({ path: path.join(SHOTS, '01-library.png') })
check('无 JS 错误', errors.length === 0, errors.slice(0, 2).join(' ;; '))

await browser.close()
console.log(`\n${fail === 0 ? '全部通过 ✅' : `${fail} 项失败 ❌`}   截图：${SHOTS}`)
await sleep(150)
process.exitCode = fail === 0 ? 0 : 1
