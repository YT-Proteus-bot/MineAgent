import puppeteer from 'puppeteer-core'
import path from 'node:path'
import os from 'node:os'
import fs from 'node:fs'

const BASE = 'http://127.0.0.1:8000'
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const SHOTS = path.join(os.tmpdir(), 'mineagent-undo')
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

const count = () => page.$$eval('.agent-node', (els) => els.length)
const undoDisabled = () =>
  page.evaluate(() => {
    const b = [...document.querySelectorAll('.topbar button')].find((x) =>
      (x.getAttribute('title') || '').includes('撤销'),
    )
    return b ? b.disabled : true
  })
const clickBtn = (kw) =>
  page.evaluate((k) => {
    const b = [...document.querySelectorAll('.topbar button')].find((x) =>
      (x.getAttribute('title') || '').includes(k),
    )
    b && b.click()
  }, kw)

console.log('\n[A] 初始状态')
check('撤销按钮存在且不可用', await undoDisabled(), '空的撤销栈')
const n0 = await count()
check('画布有节点', n0 > 0, `${n0} 个`)

console.log('\n[B] 新增节点 -> 撤销 -> 重做')
await page.mouse.click(700, 620, { button: 'right' })
await page.waitForSelector('.ctx-search input', { timeout: 6000 })
await page.type('.ctx-search input', 'memory', { delay: 15 })
await sleep(400)
await page.click('.ctx-item')
await sleep(900) // 等历史快照落一步
const n1 = await count()
check('新增了一个节点', n1 === n0 + 1, `${n0} → ${n1}`)
check('撤销按钮变为可用', !(await undoDisabled()))

await clickBtn('撤销')
await sleep(500)
const n2 = await count()
check('撤销后节点消失', n2 === n0, `${n1} → ${n2}`)
await page.screenshot({ path: path.join(SHOTS, '01-undone.png') })

await clickBtn('重做')
await sleep(500)
const n3 = await count()
check('重做后节点回来', n3 === n1, `${n2} → ${n3}`)

console.log('\n[C] Ctrl+Z / Ctrl+Shift+Z')
// 先点空白让焦点离开输入框
await page.mouse.click(400, 300)
await sleep(300)
await page.keyboard.down('Control')
await page.keyboard.press('KeyZ')
await page.keyboard.up('Control')
await sleep(500)
const n4 = await count()
check('Ctrl+Z 触发撤销', n4 === n0, `${n3} → ${n4}`)

await page.keyboard.down('Control')
await page.keyboard.down('Shift')
await page.keyboard.press('KeyZ')
await page.keyboard.up('Shift')
await page.keyboard.up('Control')
await sleep(500)
const n5 = await count()
check('Ctrl+Shift+Z 触发重做', n5 === n1, `${n4} → ${n5}`)

console.log('\n[D] 连续拖动合并成一步')
const before = await count()
const box = await (await page.$$('.agent-node'))[0].boundingBox()
await page.mouse.move(box.x + 30, box.y + 20)
await page.mouse.down()
for (let i = 1; i <= 8; i++) {
  await page.mouse.move(box.x + 30 + i * 12, box.y + 20 + i * 6)
  await sleep(40)
}
await page.mouse.up()
await sleep(900)
await clickBtn('撤销')
await sleep(500)
const afterDragUndo = await count()
check('拖动后撤销不会误删节点', afterDragUndo === before, `${before} → ${afterDragUndo}`)

check('无 JS 运行时错误', errors.length === 0, errors.slice(0, 2).join(' ;; '))

await browser.close()
console.log(`\n${fail === 0 ? '全部通过 ✅' : `${fail} 项失败 ❌`}   截图：${SHOTS}`)
await sleep(200)
process.exitCode = fail === 0 ? 0 : 1
