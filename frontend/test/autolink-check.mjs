import puppeteer from 'puppeteer-core'
import path from 'node:path'
import os from 'node:os'
import fs from 'node:fs'

const BASE = 'http://127.0.0.1:8000'
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const SHOTS = path.join(os.tmpdir(), 'mineagent-autolink')
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

const stats = () =>
  page.evaluate(() => ({
    nodes: [...document.querySelectorAll('.react-flow__node')].map((n) => n.getAttribute('data-id')),
    edges: [...document.querySelectorAll('.react-flow__edge')].map((e) => e.getAttribute('data-id')),
  }))

const addViaPicker = async (x, y, query) => {
  await page.mouse.click(x, y, { button: 'right' })
  await page.waitForSelector('.ctx-search input', { timeout: 6000 })
  await page.type('.ctx-search input', query, { delay: 15 })
  await sleep(400)
  await page.click('.ctx-item')
  await sleep(700)
}

const edgesInto = (edges, id) => edges.filter((e) => e.includes(`_${id}_`)).length

console.log('\n[A] 选中节点后新增：应插到它后面')
await page.evaluate(() => {
  const list = [...document.querySelectorAll('.agent-node')]
  const idx = list.findIndex((n) => n.querySelector('.node-kind')?.textContent === 'agent')
  list[idx]?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
})
await sleep(600)
const before = await stats()
await addViaPicker(820, 780, 'memory')
const after1 = await stats()
const newNode1 = after1.nodes.find((n) => !before.nodes.includes(n))
check('新增了节点', !!newNode1, newNode1 || '')
check('新节点自动获得了入边', newNode1 ? edgesInto(after1.edges, newNode1) > 0 : false,
  `${after1.edges.length - before.edges.length} 条新边`)
await page.screenshot({ path: path.join(SHOTS, '01-inserted.png') })

console.log('\n[B] 未选中时新增：应连到最近的可连节点')
await page.mouse.click(400, 320) // 点空白取消选中
await sleep(500)
const before2 = await stats()
await addViaPicker(560, 640, 'observation')
const after2 = await stats()
const newNode2 = after2.nodes.find((n) => !before2.nodes.includes(n))
check('新增了节点', !!newNode2)
check('新节点自动获得了入边', newNode2 ? edgesInto(after2.edges, newNode2) > 0 : false)
await page.screenshot({ path: path.join(SHOTS, '02-nearest.png') })

console.log('\n[C] 新增 output：应接到末端')
await page.mouse.click(400, 320)
await sleep(400)
const before3 = await stats()
await addViaPicker(1000, 300, '输出 Output')
const after3 = await stats()
const newNode3 = after3.nodes.find((n) => !before3.nodes.includes(n))
check('新增了 output 节点', !!newNode3)
check('output 自动获得入边', newNode3 ? edgesInto(after3.edges, newNode3) > 0 : false)

console.log('\n[D] 约束仍然合规')
const report = await page.evaluate(async () => {
  const b = [...document.querySelectorAll('.topbar button')].find((x) => x.textContent.includes('约束'))
  b && b.click()
  await new Promise((r) => setTimeout(r, 1200))
  return [...document.querySelectorAll('.cv-item.level-err')].map((e) => e.textContent.trim())
})
check('没有新增 error 级违规', report.length === 0, report.slice(0, 2).join(' | '))
check('无 JS 运行时错误', errors.length === 0, errors.slice(0, 2).join(' ;; '))

await browser.close()
console.log(`\n${fail === 0 ? '全部通过 ✅' : `${fail} 项失败 ❌`}   截图：${SHOTS}`)
await sleep(200)
process.exitCode = fail === 0 ? 0 : 1
