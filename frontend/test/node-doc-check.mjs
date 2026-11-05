import puppeteer from 'puppeteer-core'
import path from 'node:path'
import os from 'node:os'
import fs from 'node:fs'

const BASE = 'http://127.0.0.1:8000'
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const SHOTS = path.join(os.tmpdir(), 'mineagent-node-doc')
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

console.log('\n[A] 悬停画布节点：显示概念/解释/用途/编码建议')
const box = await (await page.$$('.agent-node'))[2].boundingBox()
await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
await sleep(800)
const card = await page.$('.node-tip .node-doc-card')
check('出现说明卡片', !!card)
if (card) {
  const text = await page.$eval('.node-tip .node-doc-card', (el) => el.textContent)
  for (const k of ['概念', '解释', '用途', '编码建议']) {
    check(`包含「${k}」`, text.includes(k))
  }
  const title = await page.$eval('.ndc-label', (el) => el.textContent)
  console.log(`    ${title}: ${text.slice(0, 90).replace(/\s+/g, ' ')}`)
}
await page.screenshot({ path: path.join(SHOTS, '01-node-hover.png') })

console.log('\n[B] 右键新增节点：选项悬停也显示说明')
await page.mouse.move(200, 200)
await sleep(300)
const pt = await page.evaluate(() => {
  const pane = document.querySelector('.react-flow')
  const r = pane.getBoundingClientRect()
  for (let y = r.y + 80; y < r.y + r.height - 80; y += 35) {
    for (let x = r.x + 360; x < r.x + r.width - 80; x += 35) {
      const el = document.elementFromPoint(x, y)
      if (el && el.classList && el.classList.contains('react-flow__pane')) return { x, y }
    }
  }
  return null
})
await page.mouse.click(pt.x, pt.y, { button: 'right' })
await page.waitForSelector('.ctx-search input', { timeout: 8000 })
await sleep(400)

// 悬停到「任务规划」这一项
const hovered = await page.evaluate(() => {
  const item = [...document.querySelectorAll('.ctx-menu .ctx-item')].find((e) =>
    e.textContent.includes('任务规划'),
  )
  if (!item) return null
  const r = item.getBoundingClientRect()
  item.dispatchEvent(new MouseEvent('mouseenter', { bubbles: false, clientX: r.x + 20, clientY: r.y + 10 }))
  return { label: item.textContent.trim(), x: r.x + 20, y: r.y + 10 }
})
if (hovered) {
  await page.mouse.move(hovered.x, hovered.y)
  await sleep(700)
}
const floatCard = await page.$('.ctx-menu ~ .node-doc .node-doc-card, .node-doc .node-doc-card')
check('新增面板悬停出现说明', !!floatCard, hovered ? hovered.label : '找不到选项')
if (floatCard) {
  const t = await page.$eval('.node-doc .node-doc-card', (el) => el.textContent)
  check('浮层里是说明文案', /概念/.test(t) && /编码建议/.test(t), t.slice(0, 70).replace(/\s+/g, ' '))
}
await page.screenshot({ path: path.join(SHOTS, '02-picker-hover.png') })

check('无 JS 运行时错误', errors.length === 0, errors.slice(0, 2).join(' ;; '))

await browser.close()
console.log(`\n${fail === 0 ? '全部通过 ✅' : `${fail} 项失败 ❌`}   截图：${SHOTS}`)
await sleep(200)
process.exitCode = fail === 0 ? 0 : 1
