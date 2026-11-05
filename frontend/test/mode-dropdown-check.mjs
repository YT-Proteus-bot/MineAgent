import puppeteer from 'puppeteer-core'
import path from 'node:path'
import os from 'node:os'
import fs from 'node:fs'

const BASE = 'http://127.0.0.1:8000'
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const SHOTS = path.join(os.tmpdir(), 'mineagent-modes')
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

const topButtons = () =>
  page.$$eval('.topbar button', (els) => els.map((e) => e.textContent.trim()))

console.log('\n[A] 顶部有两个下拉，模式在框架左边')
const btns = await topButtons()
const modeIdx = btns.findIndex((t) => /选择模式|单次调用|ReAct|CoT|Plan-and-Execute|反思|目标驱动/.test(t) && !t.includes('LangChain') && !t.includes('AutoGen'))
const fwIdx = btns.findIndex((t) => /LangChain|AutoGen|CrewAI|MetaGPT|Agno/.test(t))
check('找到模式下拉', modeIdx >= 0, btns[modeIdx] || '')
check('找到框架下拉', fwIdx >= 0, btns[fwIdx] || '')
check('模式在框架左边', modeIdx >= 0 && fwIdx >= 0 && modeIdx < fwIdx, `模式#${modeIdx} 框架#${fwIdx}`)

console.log('\n[B] 展开模式下拉，看到当前框架的模式')
await page.evaluate((i) => {
  document.querySelectorAll('.topbar button')[i]?.click()
}, modeIdx)
await sleep(700)
const items = await page.$$eval('.popover .menu-item', (els) =>
  els.map((e) => e.textContent.trim().slice(0, 40)),
).catch(() => [])
check('列出了模式选项', items.length > 3, `${items.length} 项`)
const hasGroup = items.some((t) => /基础|推理|循环|规划|多智能体|框架专有/.test(t))
check('带分组标签', hasGroup, items.slice(0, 3).join(' | '))
await page.screenshot({ path: path.join(SHOTS, '01-mode-menu.png') })

console.log('\n[C] 选一个模式，画布记住')
const picked = await page.evaluate(() => {
  const el = [...document.querySelectorAll('.popover .menu-item')].find((e) =>
    e.textContent.includes('CoT'),
  )
  if (!el) return ''
  el.click()
  return el.textContent.trim().slice(0, 30)
})
await sleep(1200)
const toastText = await page.$$eval('.toast', (els) => els.map((e) => e.textContent.trim()))
check('选中后提示已设置', toastText.some((t) => t.includes('画布默认模式')), toastText.slice(-1).join(''))
const btns2 = await topButtons()
check('顶部按钮显示新模式', btns2.some((t) => t.includes('CoT')), btns2[modeIdx] || '')

const saved = await page.evaluate(async () => {
  const r = await fetch('/api/canvases')
  const list = await r.json()
  const d = await (await fetch(`/api/canvases/${list[0].id}`)).json()
  return d.mode
})
check('后端也存下来了', saved === 'cot', `mode=${saved}`)

console.log('\n[D] 框架与模式的对应关系（走接口，不动画布）')
const fwModes = await page.evaluate(async () => {
  const m = await (await fetch('/api/meta')).json()
  const all = m.all_modes || []
  const out = {}
  for (const [fw, values] of Object.entries(m.framework_modes || {})) {
    out[fw] = values.map((v) => all.find((x) => x.value === v)?.label || v)
  }
  return out
})
check('十个框架都有模式清单', Object.keys(fwModes).length === 10, Object.keys(fwModes).join(', '))
check('CrewAI 是流程型模式', (fwModes.crewai || []).some((t) => /顺序接力|层级分派/.test(t)), (fwModes.crewai || []).slice(0, 4).join(' / '))
check('AutoGen 有群聊/双人对话', (fwModes.autogen || []).some((t) => /群聊|双人对话/.test(t)))
check('smolagents 有代码行动', (fwModes.smolagents || []).some((t) => /代码行动/.test(t)))

// 恢复成 react，别把测试值留在画布上
await page.evaluate(async () => {
  const list = await (await fetch('/api/canvases')).json()
  await fetch(`/api/canvases/${list[0].id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode: 'react' }),
  })
})

check('无 JS 运行时错误', errors.length === 0, errors.slice(0, 2).join(' ;; '))

await browser.close()
console.log(`\n${fail === 0 ? '全部通过 ✅' : `${fail} 项失败 ❌`}   截图：${SHOTS}`)
await sleep(200)
process.exitCode = fail === 0 ? 0 : 1
