import puppeteer from 'puppeteer-core'
import path from 'node:path'
import os from 'node:os'
import fs from 'node:fs'

const BASE = 'http://127.0.0.1:8000'
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const SHOTS = path.join(os.tmpdir(), 'mineagent-layout')
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

console.log('\n[0] 点「整理布局」')
await page.evaluate(() => {
  const b = [...document.querySelectorAll('button.hud-btn')].find((e) =>
    e.textContent.includes('整理布局'),
  )
  b && b.click()
})
await sleep(1400)
await page.screenshot({ path: path.join(SHOTS, '01-layout.png') })

const geo = await page.evaluate(() => {
  const nodes = [...document.querySelectorAll('.react-flow__node')].map((n) => {
    const r = n.getBoundingClientRect()
    const name = n.querySelector('.node-name')?.textContent || ''
    const kind = n.querySelector('.node-kind')?.textContent || ''
    return {
      id: n.getAttribute('data-id'), name, kind,
      x: r.x, y: r.y, w: r.width, h: r.height,
      cx: r.x + r.width / 2, cy: r.y + r.height / 2,
    }
  })
  const labels = [...document.querySelectorAll('.edge-chip')].map((e) => {
    const r = e.getBoundingClientRect()
    return { x: r.x, y: r.y, w: r.width, h: r.height }
  })
  const t = document.querySelector('.react-flow__viewport')?.style.transform || ''
  const m = t.match(/scale\(([\d.]+)\)/)
  const zoom = m ? parseFloat(m[1]) : 1
  return { nodes, labels, zoom }
})

const { nodes, labels, zoom } = geo

console.log('\n[1] 节点不重叠')
let overlaps = 0
const overlapPairs = []
for (let i = 0; i < nodes.length; i++) {
  for (let j = i + 1; j < nodes.length; j++) {
    const a = nodes[i]
    const b = nodes[j]
    const pad = 2 // 边缘相接不算重叠
    if (a.x + pad < b.x + b.w && b.x + pad < a.x + a.w && a.y + pad < b.y + b.h && b.y + pad < a.y + a.h) {
      overlaps++
      overlapPairs.push(
        `${a.name}(${Math.round(a.w)}x${Math.round(a.h)}) × ${b.name}(${Math.round(b.w)}x${Math.round(b.h)})`,
      )
    }
  }
}
check('任意两个节点不重叠', overlaps === 0, `${overlaps} 对重叠 / ${nodes.length} 个节点`)
overlapPairs.forEach((p) => console.log(`      重叠: ${p}`))

console.log('\n[2] 输入在左、输出在右')
const input = nodes.find((n) => n.kind === 'input')
const output = nodes.find((n) => n.kind === 'output')
check('有 input 和 output 节点', !!input && !!output)
if (input && output) {
  check('input 在最左侧', input.cx <= Math.min(...nodes.map((n) => n.cx)) + 2,
    `input x=${Math.round(input.cx)}，最左 x=${Math.round(Math.min(...nodes.map((n) => n.cx)))}`)
  check('output 在最右侧', output.cx >= Math.max(...nodes.map((n) => n.cx)) - 2,
    `output x=${Math.round(output.cx)}，最右 x=${Math.round(Math.max(...nodes.map((n) => n.cx)))}`)
}

console.log('\n[3] 层间距足够放下线上的名字')
// 注意：DOM 是屏幕坐标，要除以画布缩放才是真实间距
const cols = [...new Set(nodes.map((n) => Math.round(n.x)))].sort((a, b) => a - b)
const gaps = cols.slice(1).map((x, i) => (x - cols[i]) / zoom)
const minGap = gaps.length ? Math.min(...gaps) : 0
check('上下游间距 ≥ 280px', minGap >= 280, `最小间距 ${Math.round(minGap)}px（画布坐标），共 ${cols.length} 层`)

console.log('\n[4] 线名（分支标签）不被节点盖住')
let covered = 0
for (const lb of labels) {
  for (const n of nodes) {
    if (lb.x < n.x + n.w && n.x < lb.x + lb.w && lb.y < n.y + n.h && n.y < lb.y + lb.h) {
      covered++
      break
    }
  }
}
check('分支标签没有被节点压住', covered === 0, `${covered} 个标签被压 / 共 ${labels.length} 个`)

console.log('\n[5] 连线不压节点、交叉尽量少')
const lineStats = await page.evaluate(() => {
  const nodes = [...document.querySelectorAll('.react-flow__node')].map((n) => {
    const r = n.getBoundingClientRect()
    return { x: r.x, y: r.y, w: r.width, h: r.height }
  })
  let hits = 0
  const segs = []
  for (const el of document.querySelectorAll('.react-flow__edge-path')) {
    const len = el.getTotalLength()
    if (!len) continue
    const ctm = el.getScreenCTM()
    if (!ctm) continue
    const pts = []
    for (let i = 0; i <= 10; i++) {
      const p = el.getPointAtLength((len * i) / 10)
      const sp = new DOMPoint(p.x, p.y).matrixTransform(ctm)
      pts.push({ x: sp.x, y: sp.y })
    }
    for (let i = 3; i <= 7; i++) {
      const p = pts[i]
      if (nodes.some((n) => p.x > n.x + 4 && p.x < n.x + n.w - 4 && p.y > n.y + 4 && p.y < n.y + n.h - 4)) hits++
    }
    segs.push([pts[2], pts[8]])
  }
  // 统计直线段的交叉对数
  const cross = (a, b, c, d) => {
    const s = (p, q, r) => (q.x - p.x) * (r.y - p.y) - (q.y - p.y) * (r.x - p.x)
    const d1 = s(c, d, a), d2 = s(c, d, b), d3 = s(a, b, c), d4 = s(a, b, d)
    return ((d1 > 0 && d2 < 0) || (d1 < 0 && d2 > 0)) && ((d3 > 0 && d4 < 0) || (d3 < 0 && d4 > 0))
  }
  let xPairs = 0
  for (let i = 0; i < segs.length; i++)
    for (let j = i + 1; j < segs.length; j++)
      if (cross(segs[i][0], segs[i][1], segs[j][0], segs[j][1])) xPairs++
  return { hits, xPairs, edges: segs.length }
})
check('连线中段不压节点', lineStats.hits === 0, `${lineStats.hits} 处`)
check('连线之间交叉少', lineStats.xPairs <= 1, `${lineStats.xPairs} 对交叉 / ${lineStats.edges} 条线`)

check('无 JS 运行时错误', errors.length === 0, errors.slice(0, 2).join(' ;; '))

await browser.close()
console.log(`\n${fail === 0 ? '全部通过 ✅' : `${fail} 项失败 ❌`}   截图：${SHOTS}`)
await sleep(200)
process.exitCode = fail === 0 ? 0 : 1
