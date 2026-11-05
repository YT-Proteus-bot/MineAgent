import puppeteer from 'puppeteer-core'
import path from 'node:path'
import os from 'node:os'
import fs from 'node:fs'

const BASE = 'http://127.0.0.1:8000'
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const SHOTS = path.join(os.tmpdir(), 'mineagent-link')
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

const edgeCount = () => page.$$eval('.react-flow__edge', (els) => els.length)
const before = await edgeCount()

console.log('\n[A] 鼠标拖连线：命中区与悬停不闪烁')
// 取第一个输出来源点（节点的 source handle）
const handleInfo = await page.evaluate(() => {
  const hs = [...document.querySelectorAll('.react-flow__handle-right')]
  const h = hs[0]
  if (!h) return null
  const r = h.getBoundingClientRect()
  const cx = r.x + r.width / 2
  const cy = r.y + r.height / 2
  // 用 elementFromPoint 检查这个点命中的是不是 handle（而不是 pane）
  const hit = document.elementFromPoint(cx, cy)
  const beforeEl = document.elementFromPoint(cx - 14, cy)
  return {
    rect: { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) },
    cx, cy,
    hitClass: hit?.className?.toString?.() || '',
    outsideClass: beforeEl?.className?.toString?.() || '',
  }
})
check('找到右侧输出点', !!handleInfo, handleInfo ? JSON.stringify(handleInfo.rect) : '无')
check('输出点中心命中的是 handle', /handle/.test(handleInfo?.hitClass || ''), handleInfo?.hitClass?.slice(0, 60))

// 模拟鼠标从节点外侧接近，检查 hover 前后 hit 是否稳定（不闪烁）
const stability = await page.evaluate(async () => {
  const h = document.querySelector('.react-flow__handle-right')
  const r = h.getBoundingClientRect()
  const cx = r.x + r.width / 2
  const cy = r.y + r.height / 2
  const results = []
  for (let i = 0; i < 6; i++) {
    const el = document.elementFromPoint(cx, cy)
    results.push(/handle/.test(el?.className?.toString?.() || ''))
    await new Promise((res) => setTimeout(res, 60))
  }
  return results
})
check('连续采样命中稳定', stability.every(Boolean), stability.join(','))

// 真的拖一条线：终点落在目标节点的输入点附近
const target = await page.evaluate(() => {
  const hs = [...document.querySelectorAll('.react-flow__handle-left')]
  const h = hs[hs.length - 1]
  const r = h.getBoundingClientRect()
  return { x: r.x + r.width / 2, y: r.y + r.height / 2 }
})
await page.mouse.move(handleInfo.cx, handleInfo.cy)
await page.mouse.down()
await page.mouse.move(handleInfo.cx + 30, handleInfo.cy + 10, { steps: 5 })
await page.mouse.move(target.x, target.y, { steps: 15 })
await page.mouse.up()
await sleep(700)
const afterDrag = await edgeCount()
check('拖动输出点成功建线', afterDrag === before + 1, `${before} → ${afterDrag}`)
await page.screenshot({ path: path.join(SHOTS, '01-drag-link.png') })

console.log('\n[B] 右键连线（单端口）')
const nodes = await page.$$('.agent-node')
await nodes[1].click({ button: 'right' })
await page.waitForSelector('.ctx-menu', { timeout: 6000 })
const hasLinkItem = await page.evaluate(() =>
  [...document.querySelectorAll('.ctx-menu .ctx-item')].some((e) => e.textContent.includes('连线到其它节点')),
)
check('右键菜单有「连线到其它节点」', hasLinkItem)
await page.evaluate(() => {
  const el = [...document.querySelectorAll('.ctx-menu .ctx-item')].find((e) =>
    e.textContent.includes('连线到其它节点'),
  )
  el && el.click()
})
await sleep(600)
const targetList = await page.$$eval('.ctx-menu .ctx-item', (els) => els.map((e) => e.textContent.trim()))
check('弹出目标节点列表', targetList.length > 0, `${targetList.length} 项`)
await page.screenshot({ path: path.join(SHOTS, '02-link-targets.png') })
const before2 = await edgeCount()
await page.evaluate(() => {
  const items = [...document.querySelectorAll('.ctx-menu .ctx-item')]
  const target = items.find((e) => e.textContent.trim() && !e.textContent.includes('换个出口'))
  target && target.click()
})
await sleep(700)
const after2 = await edgeCount()
check('右键连线成功', after2 === before2 + 1, `${before2} → ${after2}`)

console.log('\n[C] 右键连线（多端口节点要先选出口）')
const routerIdx = await page.evaluate(() => {
  const list = [...document.querySelectorAll('.agent-node')]
  return list.findIndex((n) => n.querySelector('.node-kind')?.textContent === 'router')
})
if (routerIdx >= 0) {
  const hs = await page.$$('.agent-node')
  await hs[routerIdx].click({ button: 'right' })
  await page.waitForSelector('.ctx-menu', { timeout: 6000 })
  await page.evaluate(() => {
    const el = [...document.querySelectorAll('.ctx-menu .ctx-item')].find((e) =>
      e.textContent.includes('连线到其它节点'),
    )
    el && el.click()
  })
  await sleep(600)
  const branchItems = await page.$$eval('.ctx-menu .ctx-item', (els) => els.map((e) => e.textContent.trim()))
  check('多端口节点先列出出口', branchItems.some((t) => t.includes('true') || t.includes('是')), branchItems.join(' | '))
  await page.screenshot({ path: path.join(SHOTS, '03-branches.png') })
  await page.evaluate(() => {
    const el = [...document.querySelectorAll('.ctx-menu .ctx-item')].find((e) =>
      e.textContent.includes('是（true）'),
    )
    el && el.click()
  })
  await sleep(500)
  const before3 = await edgeCount()
  await page.evaluate(() => {
    // 明确挑一个目标：取列表里最后一个带 name 的候选（通常是 output 节点）
    const items = [...document.querySelectorAll('.ctx-menu .ctx-item')].filter((e) =>
      e.querySelector('.hint'),
    )
    const last = items[items.length - 1]
    last && last.click()
  })
  await sleep(700)
  const after3 = await edgeCount()
  check('选择出口后成功连线', after3 === before3 + 1, `${before3} → ${after3}`)
  await page.screenshot({ path: path.join(SHOTS, '04-linked.png') })
} else {
  check('画布上有 router 节点', false, '未找到')
}

check('无 JS 运行时错误', errors.length === 0, errors.slice(0, 2).join(' ;; '))

await browser.close()
console.log(`\n${fail === 0 ? '全部通过 ✅' : `${fail} 项失败 ❌`}   截图：${SHOTS}`)
await sleep(200)
process.exitCode = fail === 0 ? 0 : 1
