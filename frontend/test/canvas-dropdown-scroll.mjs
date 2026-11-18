import puppeteer from 'puppeteer-core'
import path from 'node:path'
import os from 'node:os'
import fs from 'node:fs'

const BASE = 'http://127.0.0.1:8000'
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const SHOTS = path.join(os.tmpdir(), 'mineagent-scroll')
fs.mkdirSync(SHOTS, { recursive: true })
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

let pass = 0
let fail = 0
const check = (n, ok, extra = '') => {
  console.log(`  ${ok ? '✔' : '✘'} ${n}${extra ? ` — ${extra}` : ''}`)
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

await page.goto(BASE, { waitUntil: 'networkidle2', timeout: 40000 })
await page.waitForSelector('.agent-node', { timeout: 25000 })
await sleep(2000)

// 打开画布下拉
await page.evaluate(() => {
  const b = [...document.querySelectorAll('.topbar button')].find((x) =>
    x.textContent.includes('选择画布') || x.querySelector('.dim.small'),
  )
  b && b.click()
})
await sleep(800)

const info = await page.evaluate(() => {
  const scroller = document.querySelector('.menu-scroll')
  const popover = document.querySelector('.popover')
  if (!scroller) return { found: false }
  const sr = scroller.getBoundingClientRect()
  const pr = popover.getBoundingClientRect()
  return {
    found: true,
    scrollHeight: scroller.scrollHeight,
    clientHeight: scroller.clientHeight,
    scrollable: scroller.scrollHeight > scroller.clientHeight + 1,
    popoverBottom: Math.round(pr.bottom),
    viewportHeight: window.innerHeight,
    itemCount: scroller.querySelectorAll('.menu-item').length,
  }
})

console.log('\n[A] 画布列表可滚动')
check('找到滚动容器', info.found)
if (info.found) {
  check('内容高度超过容器', info.scrollable, `${info.scrollHeight}px > ${info.clientHeight}px`)
  check('容器高度受限', info.clientHeight <= 470, `clientHeight=${info.clientHeight}px`)
  check('下拉没超出窗口', info.popoverBottom <= info.viewportHeight + 1,
    `bottom=${info.popoverBottom} / vh=${info.viewportHeight}`)
  check('列表项都渲染了', info.itemCount > 5, `${info.itemCount} 项`)
}

console.log('\n[B] 底部操作项仍然可见')
const actions = await page.evaluate(() => {
  const items = [...document.querySelectorAll('.popover .menu-item')]
  const names = items.map((e) => e.textContent.replace(/\s+/g, ' ').trim())
  const popover = document.querySelector('.popover').getBoundingClientRect()
  const scroller = document.querySelector('.menu-scroll').getBoundingClientRect()
  const addNew = items.find((e) => e.textContent.includes('新增画布'))
  const r = addNew ? addNew.getBoundingClientRect() : null
  return {
    hasAddNew: names.some((n) => n.includes('新增画布')),
    hasDelete: names.some((n) => n.includes('删除当前画布')),
    addNewVisible: r ? r.bottom <= popover.bottom + 1 : false,
    addNewOutsideScroll: r ? r.top >= scroller.bottom - 1 : false,
  }
})
check('有「新增画布」', actions.hasAddNew)
check('有「删除当前画布」', actions.hasDelete)
check('新增画布不在滚动区里', actions.addNewOutsideScroll)
check('新增画布在下拉可视范围内', actions.addNewVisible)

console.log('\n[C] 实际能滚')
const before = await page.evaluate(() => document.querySelector('.menu-scroll').scrollTop)
await page.evaluate(() => {
  document.querySelector('.menu-scroll').scrollTop = 400
})
await sleep(400)
const after = await page.evaluate(() => document.querySelector('.menu-scroll').scrollTop)
check('滚动位置发生变化', after > before, `${before} → ${after}`)

await page.screenshot({ path: path.join(SHOTS, '01-scrolled.png') })
check('无 JS 错误', errors.length === 0, errors.slice(0, 2).join(' ;; '))

await browser.close()
console.log(`\n${fail === 0 ? '全部通过 ✅' : `${fail} 项失败 ❌`}   截图：${SHOTS}`)
await sleep(150)
process.exitCode = fail === 0 ? 0 : 1
