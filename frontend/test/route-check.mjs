import puppeteer from 'puppeteer-core'
import path from 'node:path'
import os from 'node:os'
import fs from 'node:fs'

const BASE = 'http://127.0.0.1:8000'
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const SHOTS = path.join(os.tmpdir(), 'mineagent-route')
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

/** 统计连线中间段压在节点上的次数 */
const overlapCount = () =>
  page.evaluate(() => {
    const nodes = [...document.querySelectorAll('.react-flow__node')].map((n) => {
      const r = n.getBoundingClientRect()
      return { id: n.getAttribute('data-id'), x: r.x, y: r.y, w: r.width, h: r.height }
    })
    let hits = 0
    let checked = 0
    for (const el of document.querySelectorAll('.react-flow__edge-path')) {
      const len = el.getTotalLength()
      if (!len) continue
      const ctm = el.getScreenCTM()
      if (!ctm) continue
      const toScreen = (pt) => {
        const sp = new DOMPoint(pt.x, pt.y).matrixTransform(ctm)
        return { x: sp.x, y: sp.y }
      }
      const startPt = toScreen(el.getPointAtLength(0))
      const endPt = toScreen(el.getPointAtLength(len))
      const nodeAt = (p) =>
        nodes.find(
          (n) =>
            p.x >= n.x - 10 && p.x <= n.x + n.w + 10 && p.y >= n.y - 10 && p.y <= n.y + n.h + 10,
        )
      const srcNode = nodeAt(startPt)
      const dstNode = nodeAt(endPt)
      // 两端节点在水平方向有重叠时，边必须从右往左回溯、必然贴着目标节点，路由无解，跳过
      const xOverlap =
        srcNode &&
        dstNode &&
        srcNode !== dstNode &&
        srcNode.x + srcNode.w > dstNode.x &&
        dstNode.x + dstNode.w > srcNode.x
      if (xOverlap) continue
      for (let i = 0; i <= 20; i++) {
        const p = el.getPointAtLength((len * i) / 20)
        const sp = new DOMPoint(p.x, p.y).matrixTransform(ctm)
        // 距两端 handle 太近的点跳过：连线必然贴着起止节点，那不算压节点
        const d0 = Math.hypot(sp.x - startPt.x, sp.y - startPt.y)
        const d1 = Math.hypot(sp.x - endPt.x, sp.y - endPt.y)
        if (d0 < 55 || d1 < 55) continue
        for (const n of nodes) {
          const pad = 3
          if (
            sp.x > n.x + pad &&
            sp.x < n.x + n.w - pad &&
            sp.y > n.y + pad &&
            sp.y < n.y + n.h - pad
          ) {
            hits++
            break
          }
        }
        checked++
      }
    }
    return { hits, checked, edges: document.querySelectorAll('.react-flow__edge').length }
  })

console.log('\n[A] 连线绕开节点')
const before = await overlapCount()
check('画布有连线', before.edges > 0, `${before.edges} 条`)
check('连线中间段没有压在节点上', before.hits === 0, `${before.hits} 处重叠 / ${before.checked} 个采样点`)
await page.screenshot({ path: path.join(SHOTS, '01-initial.png') })

console.log('\n[B] 拖动节点后仍然绕开')
const nodes = await page.$$('.agent-node')
const box = await nodes[2].boundingBox()
await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
await page.mouse.down()
await page.mouse.move(box.x + box.width / 2 + 60, box.y + box.height / 2 - 120, { steps: 12 })
await page.mouse.up()
await sleep(900)
const after = await overlapCount()
check('拖动后连线自动重新绕行', after.hits === 0, `${after.hits} 处重叠 / ${after.checked} 个采样点`)
await page.screenshot({ path: path.join(SHOTS, '02-after-drag.png') })

console.log('\n[C] 强行把节点拖到线中间，线应重算')
const box2 = await nodes[4].boundingBox()
await page.mouse.move(box2.x + box2.width / 2, box2.y + box2.height / 2)
await page.mouse.down()
await page.mouse.move(box2.x + box2.width / 2, box2.y + box2.height / 2 + 150, { steps: 12 })
await page.mouse.up()
await sleep(900)
const after2 = await overlapCount()
check('新位置下依然不压节点', after2.hits === 0, `${after2.hits} 处重叠`)
await page.screenshot({ path: path.join(SHOTS, '03-moved.png') })

check('无 JS 运行时错误', errors.length === 0, errors.slice(0, 2).join(' ;; '))

await browser.close()
console.log(`\n${fail === 0 ? '全部通过 ✅' : `${fail} 项失败 ❌`}   截图：${SHOTS}`)
await sleep(200)
process.exitCode = fail === 0 ? 0 : 1
