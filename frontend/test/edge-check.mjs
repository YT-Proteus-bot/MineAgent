import puppeteer from 'puppeteer-core'
import path from 'node:path'
import os from 'node:os'
import fs from 'node:fs'

const BASE = 'http://127.0.0.1:8000'
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const SHOTS = path.join(os.tmpdir(), 'mineagent-edges')
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

const stat = async () => {
  return await page.evaluate(() => {
    const paths = [...document.querySelectorAll('.react-flow__edge-path')]
    const dashed = paths.filter((p) => (p.style.strokeDasharray || '').includes('6')).length
    const chips = document.querySelectorAll('.edge-chip').length
    const nodes = [...document.querySelectorAll('.agent-node')].map((n) => {
      const r = n.getBoundingClientRect()
      return { x: Math.round(r.x), y: Math.round(r.y) }
    })
    return { edges: paths.length, dashed, chips, nodes }
  })
}

console.log('\n[A] 连线渲染')
const before = await stat()
check('所有边都用自定义走线', before.edges > 0, `${before.edges} 条`)
check('分支标签渲染为 chip', before.chips > 0, `${before.chips} 个`)

// 造一条回边：右键最后一个节点，连回第一个节点
await page.evaluate(() => {
  const list = [...document.querySelectorAll('.agent-node')]
  list[list.length - 1]?.dispatchEvent(
    new MouseEvent('contextmenu', { bubbles: true, clientX: 700, clientY: 500 }),
  )
})
await page.waitForSelector('.ctx-menu', { timeout: 6000 })
await page.evaluate(() => {
  const el = [...document.querySelectorAll('.ctx-menu .ctx-item')].find((e) =>
    e.textContent.includes('连线到其它节点'),
  )
  el && el.click()
})
await sleep(500)
await page.evaluate(() => {
  const items = [...document.querySelectorAll('.ctx-menu .ctx-item')].filter((e) =>
    e.querySelector('.hint'),
  )
  items[0] && items[0].click()
})
await sleep(900)
const withBack = await stat()
check('造出一条回边后出现虚线', withBack.dashed > 0, `${withBack.dashed} 条虚线 / 共 ${withBack.edges} 条`)
await page.screenshot({ path: path.join(SHOTS, '01-before.png') })

console.log('\n[B] 整理布局')
const posBefore = JSON.stringify(before.nodes)
await page.evaluate(() => {
  const b = [...document.querySelectorAll('button.hud-btn')].find((e) => e.textContent.includes('整理布局'))
  b && b.click()
})
await sleep(1200)
const after = await stat()
check('节点位置被重排', JSON.stringify(after.nodes) !== posBefore, `${after.nodes.length} 个节点`)
check('连线数量不变', after.edges === withBack.edges, `${withBack.edges} → ${after.edges}`)
check('没有产生运行时错误', errors.length === 0, errors.slice(0, 2).join(' ;; '))
await page.screenshot({ path: path.join(SHOTS, '02-after-layout.png') })

// 不做 reload：测试里的改动没有保存，关掉浏览器就丢弃了
await browser.close()
console.log(`\n${fail === 0 ? '全部通过 ✅' : `${fail} 项失败 ❌`}   截图：${SHOTS}`)
await sleep(200)
process.exitCode = fail === 0 ? 0 : 1
