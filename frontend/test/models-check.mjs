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

const clickFetch = async () => {
  const clicked = await page.evaluate(() => {
    const b = [...document.querySelectorAll('.modal button')].find((x) =>
      x.textContent.includes('获取列表'),
    )
    b && b.click()
    return !!b
  })
  return clicked
}

const optionCount = () =>
  page.$$eval('.modal datalist option', (els) => els.length).catch(() => 0)

console.log('\n[A] 用户中心：填好 key 后获取模型列表')
await openUserCenter()
check('有「获取列表」按钮', await clickFetch())
await page.waitForFunction(
  () => [...document.querySelectorAll('.toast')].some((t) => t.textContent.includes('模型')),
  { timeout: 40000, polling: 300 },
).catch(() => {})
await sleep(800)
const n1 = await optionCount()
const msg1 = await page.$$eval('.toast', (els) => els.map((e) => e.textContent.trim()))
check('拉到模型并填入下拉候选', n1 > 0, `${n1} 个候选`)
check('有成功提示', msg1.some((m) => m.includes('获取到')), msg1.slice(-1).join(''))
const models = await page.$$eval('.modal datalist option', (els) =>
  els.slice(0, 5).map((e) => e.getAttribute('value')),
)
console.log('    候选示例:', models.join(', '))
await page.screenshot({ path: path.join(SHOTS, '01-user-center.png') })
await page.keyboard.press('Escape')
await sleep(500)

console.log('\n[B] 画布模型弹窗：同样可以获取')
await openCanvasModel()
check('画布弹窗也有「获取列表」', await clickFetch())
await page.waitForFunction(
  () => [...document.querySelectorAll('.toast')].some((t) => t.textContent.includes('模型')),
  { timeout: 40000, polling: 300 },
).catch(() => {})
await sleep(800)
const n2 = await optionCount()
check('画布弹窗填入了候选', n2 > 0, `${n2} 个候选`)
await page.screenshot({ path: path.join(SHOTS, '02-canvas-model.png') })
await page.keyboard.press('Escape')
await sleep(400)

console.log('\n[C] 节点模型弹窗：同样可以获取')
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
check('节点弹窗也有「获取列表」', await clickFetch())
await page.waitForFunction(
  () => [...document.querySelectorAll('.toast')].some((t) => t.textContent.includes('模型')),
  { timeout: 40000, polling: 300 },
).catch(() => {})
await sleep(800)
const n3 = await optionCount()
check('节点弹窗填入了候选', n3 > 0, `${n3} 个候选`)
await page.screenshot({ path: path.join(SHOTS, '03-node-model.png') })

check('无 JS 运行时错误', errors.length === 0, errors.slice(0, 2).join(' ;; '))

await browser.close()
console.log(`\n${fail === 0 ? '全部通过 ✅' : `${fail} 项失败 ❌`}   截图：${SHOTS}`)
await sleep(200)
process.exitCode = fail === 0 ? 0 : 1
