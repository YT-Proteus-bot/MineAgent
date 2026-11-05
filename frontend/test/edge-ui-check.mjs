import puppeteer from 'puppeteer-core'
import path from 'node:path'
import os from 'node:os'
import fs from 'node:fs'

const BASE = 'http://127.0.0.1:8000'
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const SHOTS = path.join(os.tmpdir(), 'mineagent-edge-ui')
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

const highlightedCount = () =>
  page.$$eval('.agent-node.highlighted', (els) => els.length)
const pathD = () =>
  page.$eval('.react-flow__edge-path', (el) => el.getAttribute('d') || '').catch(() => '')
const toasts = () =>
  page.$$eval('.toast', (els) => els.map((e) => e.textContent.trim())).catch(() => [])

console.log('\n[A] 点击连线高亮两端节点')
const edgeBox = await page.$eval('.react-flow__edge', (el) => {
  const r = el.getBoundingClientRect()
  return { x: r.x + r.width / 2, y: r.y + r.height / 2 }
})
await page.mouse.click(edgeBox.x, edgeBox.y)
await sleep(600)
const hl = await highlightedCount()
check('点击后两端节点高亮', hl === 2, `${hl} 个高亮节点`)
await page.screenshot({ path: path.join(SHOTS, '01-edge-click.png') })

console.log('\n[B] 连线中点手柄可拖动')
const hasHandle = await page.$('.edge-drag')
check('选中后出现拖动手柄', !!hasHandle)
const dBefore = await pathD()
if (hasHandle) {
  const hb = await hasHandle.boundingBox()
  await page.mouse.move(hb.x + hb.width / 2, hb.y + hb.height / 2)
  await page.mouse.down()
  await page.mouse.move(hb.x + hb.width / 2 + 90, hb.y + hb.height / 2 + 70, { steps: 10 })
  await page.mouse.up()
  await sleep(600)
}
const dAfter = await pathD()
check('拖动后连线路径变化', dBefore !== dAfter, `${dBefore.slice(0, 24)}… → ${dAfter.slice(0, 24)}…`)
const edgeCount = await page.$$eval('.react-flow__edge', (els) => els.length)
check('连接关系未变（边数量不变）', edgeCount > 0, `${edgeCount} 条`)
await page.screenshot({ path: path.join(SHOTS, '02-edge-drag.png') })

console.log('\n[C] 右键连线改起点')
const edgeBox2 = await page.$eval('.react-flow__edge', (el) => {
  const r = el.getBoundingClientRect()
  return { x: r.x + r.width / 2, y: r.y + r.height / 2 }
})
await page.mouse.click(edgeBox2.x, edgeBox2.y, { button: 'right' })
await page.waitForSelector('.ctx-menu', { timeout: 6000 })
const menuText = await page.$$eval('.ctx-menu .ctx-item', (els) =>
  els.map((e) => e.textContent.trim()),
)
check('右键出现连线菜单', menuText.some((t) => t.includes('修改起点')), menuText.join(' | '))
await page.evaluate(() => {
  const el = [...document.querySelectorAll('.ctx-menu .ctx-item')].find((e) =>
    e.textContent.includes('修改起点'),
  )
  el && el.click()
})
await sleep(500)
const nodeOptions = await page.$$eval('.ctx-menu .ctx-item', (els) => els.length)
check('列出可选的新起点', nodeOptions > 0, `${nodeOptions} 个候选`)
await page.screenshot({ path: path.join(SHOTS, '03-edge-menu.png') })

// 选一个既不是当前起点、也不是当前终点的节点，避免撞上「两端相同」的保护
const pick = await page.evaluate(() => {
  const edgeId = document.querySelector('.react-flow__edge')?.getAttribute('data-id') || ''
  const m = edgeId.match(/^e_(.+?)_(out|true|false|loop|exit|yes|no|approve|reject)_(.+?)_[a-z0-9]+_[a-z0-9]+$/)
  const srcName = m
    ? document.querySelector(`.react-flow__node[data-id="${m[1]}"] .node-name`)?.textContent
    : ''
  const dstName = m
    ? document.querySelector(`.react-flow__node[data-id="${m[3]}"] .node-name`)?.textContent
    : ''
  const items = [...document.querySelectorAll('.ctx-menu .ctx-item')].filter((e) =>
    e.querySelector('.hint'),
  )
  const target = items.find((e) => {
    const hint = e.querySelector('.hint')?.textContent || ''
    return hint !== srcName && hint !== dstName
  })
  if (target) {
    target.click()
    return target.querySelector('.hint')?.textContent || 'clicked'
  }
  return ''
})
console.log('    选了新起点:', pick)
await sleep(900)
const t = await toasts()
check('改起点后有反馈', t.some((x) => x.includes('起点已改为')), t.slice(-2).join(' | '))
check('边数量仍然一致', (await page.$$eval('.react-flow__edge', (els) => els.length)) === edgeCount)

check('无 JS 运行时错误', errors.length === 0, errors.slice(0, 2).join(' ;; '))

await browser.close()
console.log(`\n${fail === 0 ? '全部通过 ✅' : `${fail} 项失败 ❌`}   截图：${SHOTS}`)
await sleep(200)
process.exitCode = fail === 0 ? 0 : 1
