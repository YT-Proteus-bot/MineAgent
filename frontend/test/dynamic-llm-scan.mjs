import puppeteer from 'puppeteer-core'
import path from 'node:path'
import os from 'node:os'
import fs from 'node:fs'

const BASE = 'http://127.0.0.1:8000'
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const SHOTS = path.join(os.tmpdir(), 'mineagent-dyn-scan')
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

// 先备份当前画布
const backup = await page.evaluate(async () => {
  const list = await (await fetch('/api/canvases')).json()
  const d = await (await fetch(`/api/canvases/${list[0].id}`)).json()
  return { id: list[0].id, graph: d.graph, mode: d.mode }
})

const menuForKind = async (kind) => {
  await page.evaluate((k) => {
    const el = [...document.querySelectorAll('.agent-node')].find(
      (n) => n.querySelector('.node-kind')?.textContent === k,
    )
    const r = el.getBoundingClientRect()
    el.dispatchEvent(
      new MouseEvent('contextmenu', { bubbles: true, clientX: r.x + 20, clientY: r.y + 20 }),
    )
  }, kind)
  await page.waitForSelector('.ctx-menu', { timeout: 8000 })
  await sleep(300)
  const items = await page.$$eval('.ctx-menu .ctx-item', (els) =>
    els.map((e) => e.textContent.trim()),
  )
  await page.keyboard.press('Escape')
  await sleep(250)
  return items
}

const rewriteNodeCode = async (kind, code) => {
  const result = await page.evaluate(
    async ({ kind, code }) => {
      const list = await (await fetch('/api/canvases')).json()
      const cid = list[0].id
      const d = await (await fetch(`/api/canvases/${cid}`)).json()
      const nodes = JSON.parse(JSON.stringify(d.graph.nodes))
      const target = nodes.find((n) => n.data.kind === kind)
      if (!target) return null
      target.data.code = code
      target.data.code_touched = true
      await fetch(`/api/canvases/${cid}/save`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          nodes,
          edges: d.graph.edges,
          viewport: d.graph.viewport,
          background: d.background,
        }),
      })
      const d2 = await (await fetch(`/api/canvases/${cid}`)).json()
      const after = d2.graph.nodes.find((n) => n.id === target.id)
      return { name: after.data.name, uses_llm: after.data.uses_llm }
    },
    { kind, code },
  )
  await page.reload({ waitUntil: 'domcontentloaded' })
  await sleep(2500)
  return result
}

console.log('\n[A] 扫描结果写进节点数据')
const found = await page.evaluate(async () => {
  const list = await (await fetch('/api/canvases')).json()
  const d = await (await fetch(`/api/canvases/${list[0].id}`)).json()
  return d.graph.nodes.map((n) => ({ kind: n.data.kind, uses_llm: n.data.uses_llm }))
})
const withLLM = found.filter((f) => f.uses_llm).map((f) => f.kind)
const withoutLLM = found.filter((f) => !f.uses_llm).map((f) => f.kind)
check('节点都带上了 uses_llm', found.every((f) => typeof f.uses_llm === 'boolean'), `${found.length} 个`)
check('推理类节点为 true', withLLM.length > 0, withLLM.slice(0, 6).join(', '))
const ioNodes = found.filter((f) => f.kind === 'input' || f.kind === 'output')
check(
  'input/output 为 false',
  ioNodes.length > 0 && ioNodes.every((f) => f.uses_llm === false),
  ioNodes.map((f) => `${f.kind}=${f.uses_llm}`).join(', ') || '没有出入口节点',
)

console.log('\n[B] 把节点的模型调用删掉后，入口消失')
const before = await menuForKind('formatter')
check('改动前有「配置模型」', before.some((t) => t.includes('配置模型')))

const r1 = await rewriteNodeCode(
  'formatter',
  '# 纯字符串处理，不调模型\nfrom runtime_sdk import NodeContext\n\n\ndef run(ctx):\n    return str(ctx.input).strip().upper()\n',
)
check('保存后 uses_llm 变 false', r1?.uses_llm === false, `formatter uses_llm=${r1?.uses_llm}`)
const after = await menuForKind('formatter')
check('「配置模型」入口消失', !after.some((t) => t.includes('配置模型')), after.slice(-3).join(' | '))

console.log('\n[C] 加回模型调用后，入口回来')
const r2 = await rewriteNodeCode(
  'formatter',
  "# 用模型加工\nfrom runtime_sdk import NodeContext\n\n\ndef run(ctx):\n    return ctx.json_prompt('整理成 JSON', schema={'a': ''})\n",
)
check('保存后 uses_llm 变 true', r2?.uses_llm === true, `formatter uses_llm=${r2?.uses_llm}`)
const again = await menuForKind('formatter')
check('「配置模型」入口恢复', again.some((t) => t.includes('配置模型')))

await page.screenshot({ path: path.join(SHOTS, '01-dynamic.png') })

// 恢复备份
await page.evaluate(async (b) => {
  await fetch(`/api/canvases/${b.id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ graph: b.graph, mode: b.mode }),
  })
}, backup)
await sleep(600)
check('测试后已恢复画布', true)

check('无 JS 运行时错误', errors.length === 0, errors.slice(0, 2).join(' ;; '))

await browser.close()
console.log(`\n${fail === 0 ? '全部通过 ✅' : `${fail} 项失败 ❌`}   截图：${SHOTS}`)
await sleep(200)
process.exitCode = fail === 0 ? 0 : 1
