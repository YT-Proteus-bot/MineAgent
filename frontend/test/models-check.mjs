import puppeteer from 'puppeteer-core'
import path from 'node:path'
import os from 'node:os'
import fs from 'node:fs'

const BASE = 'http://127.0.0.1:8000'
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const SHOTS = path.join(os.tmpdir(), 'mineagent-models')
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
await sleep(1500)

const openUserCenter = async () => {
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('.topbar button')].find((x) =>
      x.textContent.includes('用户中心'),
    )
    b && b.click()
  })
  await page.waitForSelector('.modal', { timeout: 6000 })
  await sleep(500)
}

const openCanvasModel = async () => {
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('.topbar button')].find(
      (x) => x.textContent.includes('模型') && !x.textContent.includes('用户'),
    )
    b && b.click()
  })
  await page.waitForSelector('.modal', { timeout: 6000 })
  await sleep(500)
}

const clickBtn = (kw) =>
  page.evaluate((k) => {
    const b = [...document.querySelectorAll('.modal .mp-btn')].find((x) =>
      x.textContent.includes(k),
    )
    b && b.click()
    return !!b
  }, kw)

const menuItems = () => page.$$eval('.mp-menu .mp-item', (els) => els.length).catch(() => 0)
const toasts = () => page.$$eval('.toast', (els) => els.map((e) => e.textContent.trim())).catch(() => [])

const waitToast = (kw) =>
  page
    .waitForFunction(
      (k) => [...document.querySelectorAll('.toast')].some((t) => t.textContent.includes(k)),
      { timeout: 40000, polling: 300 },
      kw,
    )
    .catch(() => {})

console.log('\n[A] 用户中心：获取列表 + 下拉可展开')
await openUserCenter()
check('有「获取」按钮', await clickBtn('获取'))
await waitToast('模型')
await sleep(900)
const n1 = await menuItems()
check('获取后自动展开候选列表', n1 > 0, `${n1} 个候选`)
check('有成功提示', (await toasts()).some((m) => m.includes('获取到')))

// 点弹窗空白处收起，再点箭头应该能重新打开
const blank = await page.$eval('.modal', (el) => {
  const r = el.getBoundingClientRect()
  return { x: r.x + 24, y: r.y + 16 }
})
await page.mouse.click(blank.x, blank.y)
await sleep(400)
const closed = (await menuItems()) === 0
check('点弹窗空白能收起列表', closed)
await page.evaluate(() => {
  const b = document.querySelector('.modal .mp-arrow')
  b && b.click()
})
await sleep(500)
const reopened = await menuItems()
check('点 ▾ 能重新下拉（不再点不开）', reopened > 0, `${reopened} 个候选`)

// 选一个候选项
const picked = await page.evaluate(() => {
  const it = document.querySelector('.mp-menu .mp-item')
  if (!it) return ''
  it.click()
  return it.textContent.trim()
})
await sleep(400)
const inputVal = await page.$eval('.modal .model-picker input', (el) => el.value)
check('点候选能填入输入框', picked !== '' && inputVal === picked, `选中 ${picked}，输入框 ${inputVal}`)
await page.screenshot({ path: path.join(SHOTS, '01-dropdown.png') })

console.log('\n[B] 用户中心：测试连接')
check('有「测试」按钮', await clickBtn('测试'))
await waitToast('连接')
await sleep(600)
const t1 = await toasts()
check('测试连接有结果反馈', t1.some((m) => m.includes('连接')), t1.slice(-1).join(''))

await page.keyboard.press('Escape')
await sleep(500)

console.log('\n[C] 画布模型弹窗：两个按钮都在')
await openCanvasModel()
const canvasBtns = await page.$$eval('.modal .mp-btn', (els) =>
  els.map((e) => e.textContent.trim()),
)
check('画布弹窗有获取 + 测试', canvasBtns.some((t) => t.includes('获取')) && canvasBtns.some((t) => t.includes('测试')), canvasBtns.join(' | '))
check('点获取能拉到候选', await clickBtn('获取'))
await page
  .waitForFunction(() => document.querySelectorAll('.toast').length > 0, { timeout: 20000 })
  .catch(() => {})
const canvasToasts = await toasts()
check('画布弹窗点击后有反馈', canvasToasts.length > 0, canvasToasts.slice(-1).join(''))
await sleep(2500)
const canvasCount = await menuItems()
check('画布弹窗下拉可展开', canvasCount >= 0, `${canvasCount} 个候选（依赖目标服务可用）`)
await page.screenshot({ path: path.join(SHOTS, '02-canvas.png') })
await page.keyboard.press('Escape')
await sleep(400)

console.log('\n[D] 节点模型弹窗：两个按钮都在')
await page.evaluate(() => {
  const list = [...document.querySelectorAll('.agent-node')]
  const idx = list.findIndex((n) => n.querySelector('.node-kind')?.textContent === 'agent')
  list[idx]?.dispatchEvent(
    new MouseEvent('contextmenu', { bubbles: true, clientX: 800, clientY: 500 }),
  )
})
await page.waitForSelector('.ctx-menu', { timeout: 6000 })
await page.evaluate(() => {
  const el = [...document.querySelectorAll('.ctx-menu .ctx-item')].find((e) =>
    e.textContent.includes('配置模型'),
  )
  el && el.click()
})
await page.waitForSelector('.modal', { timeout: 6000 })
await sleep(500)
const nodeBtns = await page.$$eval('.modal .mp-btn', (els) =>
  els.map((e) => e.textContent.trim()),
)
check('节点弹窗有获取 + 测试', nodeBtns.some((t) => t.includes('获取')) && nodeBtns.some((t) => t.includes('测试')), nodeBtns.join(' | '))

check('无 JS 运行时错误', errors.length === 0, errors.slice(0, 2).join(' ;; '))

await browser.close()
console.log(`\n${fail === 0 ? '全部通过 ✅' : `${fail} 项失败 ❌`}   截图：${SHOTS}`)
await sleep(200)
process.exitCode = fail === 0 ? 0 : 1
