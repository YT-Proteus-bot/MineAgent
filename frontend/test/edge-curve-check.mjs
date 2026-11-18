import puppeteer from 'puppeteer-core'
import path from 'node:path'
import os from 'node:os'
import fs from 'node:fs'

const BASE = 'http://127.0.0.1:8000'
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const SHOTS = path.join(os.tmpdir(), 'mineagent-curve')
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

// 取第一条边的路径端点（屏幕坐标）
const readEdge = () =>
  page.evaluate(() => {
    const el = document.querySelector('.react-flow__edge-path')
    if (!el) return null
    const len = el.getTotalLength()
    const ctm = el.getScreenCTM()
    const at = (t) => {
      const p = el.getPointAtLength(len * t)
      const sp = new DOMPoint(p.x, p.y).matrixTransform(ctm)
      return { x: Math.round(sp.x), y: Math.round(sp.y) }
    }
    return { start: at(0), end: at(1), mid: at(0.5), edgeId: el.parentElement.getAttribute('data-id') }
  })

console.log('\n[A] 点击线选中')
const before = await readEdge()
check('找到连线', !!before, before ? `${before.start.x},${before.start.y} → ${before.end.x},${before.end.y}` : '')

// 点中点选中
await page.mouse.click(before.mid.x, before.mid.y)
await sleep(700)
const selected = await page.evaluate(() => {
  const g = document.querySelector('.react-flow__edge.selected')
  return !!g
})
check('点击后连线被选中', selected)

console.log('\n[B] 拖动线本身调整曲度（选中状态下）')
const b = await readEdge()
await page.mouse.move(b.mid.x, b.mid.y)
await page.mouse.down()
await page.mouse.move(b.mid.x, b.mid.y + 90, { steps: 12 })
await page.mouse.up()
await sleep(600)

const after = await readEdge()
check('曲线中点移动了（曲度变化）', after && Math.abs(after.mid.y - b.mid.y) > 20,
  after ? `mid y: ${b.mid.y} → ${after.mid.y}` : '')

console.log('\n[C] 起点终点必须保持不变')
if (after) {
  const ds = Math.hypot(after.start.x - before.start.x, after.start.y - before.start.y)
  const de = Math.hypot(after.end.x - before.end.x, after.end.y - before.end.y)
  check('起点没动', ds <= 2, `偏移 ${ds.toFixed(1)}px`)
  check('终点没动', de <= 2, `偏移 ${de.toFixed(1)}px`)
}
await page.screenshot({ path: path.join(SHOTS, '01-curved.png') })

console.log('\n[D] 右键重置弯曲')
const c = await readEdge()
await page.mouse.click(c.mid.x, c.mid.y, { button: 'right' })
await page.waitForSelector('.ctx-menu', { timeout: 6000 })
await page.evaluate(() => {
  const el = [...document.querySelectorAll('.ctx-menu .ctx-item')].find((e) =>
    e.textContent.includes('重置弯曲'),
  )
  el && el.click()
})
await sleep(700)
const reset = await readEdge()
const backToStraight = reset && Math.abs(reset.mid.y - before.mid.y) < 12
check('重置后回到默认走向', backToStraight, reset ? `mid y=${reset.mid.y}（原始 ${before.mid.y}）` : '')
await page.screenshot({ path: path.join(SHOTS, '02-reset.png') })

check('无 JS 运行时错误', errors.length === 0, errors.slice(0, 2).join(' ;; '))

await browser.close()
console.log(`\n${fail === 0 ? '全部通过 ✅' : `${fail} 项失败 ❌`}   截图：${SHOTS}`)
await sleep(200)
process.exitCode = fail === 0 ? 0 : 1
