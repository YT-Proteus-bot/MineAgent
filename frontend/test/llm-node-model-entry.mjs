import puppeteer from 'puppeteer-core'
import path from 'node:path'
import os from 'node:os'
import fs from 'node:fs'

const BASE = 'http://127.0.0.1:8000'
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const SHOTS = path.join(os.tmpdir(), 'mineagent-llm-node')
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

// 在空白处右键加一个节点（不保存，测完刷新丢弃）
const addNode = async (query) => {
  const pt = await page.evaluate(() => {
    const pane = document.querySelector('.react-flow')
    const r = pane.getBoundingClientRect()
    for (let y = r.y + 80; y < r.y + r.height - 80; y += 30) {
      for (let x = r.x + 60; x < r.x + r.width - 60; x += 30) {
        const el = document.elementFromPoint(x, y)
        if (el && el.classList && el.classList.contains('react-flow__pane')) return { x, y }
      }
    }
    return null
  })
  await page.mouse.click(pt.x, pt.y, { button: 'right' })
  await page.waitForSelector('.ctx-search input', { timeout: 8000 })
  await page.type('.ctx-search input', query, { delay: 15 })
  await sleep(500)
  await page.click('.ctx-item')
  await sleep(900)
}

const menuOfLastNode = async () => {
  await page.evaluate(() => {
    const list = [...document.querySelectorAll('.agent-node')]
    const last = list[list.length - 1]
    const r = last.getBoundingClientRect()
    last.dispatchEvent(
      new MouseEvent('contextmenu', { bubbles: true, clientX: r.x + 20, clientY: r.y + 20 }),
    )
  })
  await page.waitForSelector('.ctx-menu', { timeout: 8000 })
  await sleep(300)
  const items = await page.$$eval('.ctx-menu .ctx-item', (els) =>
    els.map((e) => e.textContent.trim()),
  )
  await page.keyboard.press('Escape')
  await sleep(250)
  return items
}

console.log('\n[A] 使用大模型的节点都能配模型')
for (const [query, label, shouldHave] of [
  ['评审', 'critic', true],
  ['反思', 'reflector', true],
  ['质量评估', 'evaluator', true],
  ['工具 Tool', 'tool', false],
]) {
  await addNode(query)
  const items = await menuOfLastNode()
  const has = items.some((t) => t.includes('配置模型'))
  check(`${label} → ${shouldHave ? '有' : '无'}「配置模型」`, has === shouldHave, items.slice(-3).join(' | '))
}

console.log('\n[B] 检查一批易漏的节点')
const kinds = await page.evaluate(async () => {
  const m = await (await fetch('/api/meta')).json()
  const pick = ['critic', 'reflector', 'evaluator', 'summarizer', 'translator',
    'classifier', 'extractor', 'polisher', 'fact_checker', 'title_generator',
    'json_repair', 'sentiment', 'doc_grader', 'query_rewrite', 'outline_builder']
  return pick.map((k) => {
    const n = m.nodes.find((x) => x.kind === k)
    return { kind: k, uses_llm: n?.uses_llm }
  })
})
const missing = kinds.filter((k) => !k.uses_llm).map((k) => k.kind)
check('常见推理类节点都标记为 uses_llm', missing.length === 0, missing.join(', ') || '全部标记')
const llmCount = await page.evaluate(async () => {
  const m = await (await fetch('/api/meta')).json()
  return m.nodes.filter((n) => n.uses_llm).length
})
check('全量统计', llmCount >= 40, `${llmCount} 个节点会调用模型`)

await page.screenshot({ path: path.join(SHOTS, '01-menu.png') })
check('无 JS 运行时错误', errors.length === 0, errors.slice(0, 2).join(' ;; '))

await browser.close()
console.log(`\n${fail === 0 ? '全部通过 ✅' : `${fail} 项失败 ❌`}   截图：${SHOTS}`)
await sleep(200)
process.exitCode = fail === 0 ? 0 : 1
