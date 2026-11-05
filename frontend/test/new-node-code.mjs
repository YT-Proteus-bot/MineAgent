import puppeteer from 'puppeteer-core'
import path from 'node:path'
import os from 'node:os'
import fs from 'node:fs'

const BASE = 'http://127.0.0.1:8000'
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const SHOTS = path.join(os.tmpdir(), 'mineagent-new-node')
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

const addNode = async (query) => {
  // 找一个真正的空白点再右键，避免点到节点
  const pt = await page.evaluate(() => {
    const pane = document.querySelector('.react-flow')
    if (!pane) return null
    const r = pane.getBoundingClientRect()
    for (let y = r.y + 60; y < r.y + r.height - 60; y += 35) {
      for (let x = r.x + 60; x < r.x + r.width - 60; x += 35) {
        const el = document.elementFromPoint(x, y)
        if (el && el.classList && el.classList.contains('react-flow__pane')) {
          return { x, y }
        }
      }
    }
    return null
  })
  if (!pt) throw new Error('找不到空白处')
  await page.mouse.click(pt.x, pt.y, { button: 'right' })
  await page.waitForSelector('.ctx-search input', { timeout: 8000 })
  await page.type('.ctx-search input', query, { delay: 15 })
  await sleep(500)
  await page.click('.ctx-item')
  await sleep(900)
}

const openCodeOfLastNode = async () => {
  await page.evaluate(() => {
    const list = [...document.querySelectorAll('.agent-node')]
    list[list.length - 1]?.dispatchEvent(
      new MouseEvent('contextmenu', { bubbles: true, clientX: 700, clientY: 600 }),
    )
  })
  await page.waitForSelector('.ctx-menu', { timeout: 6000 })
  await page.evaluate(() => {
    const el = [...document.querySelectorAll('.ctx-menu .ctx-item')].find((e) =>
      e.textContent.includes('编辑代码'),
    )
    el && el.click()
  })
  await sleep(1000)
  return page.evaluate(() => document.querySelector('.inspector textarea')?.value || '')
}

console.log('\n[A] 新增节点：未保存时代的代码就是原生块')
await addNode('任务规划')
const code1 = await openCodeOfLastNode()
check('代码不为空', code1.length > 0, `${code1.length} 字符`)
check('不再是 runtime_sdk 模板', !code1.includes('runtime_sdk') && !code1.includes('def run(ctx'))
check('是 agent.py 原生块', /def \w+\(state: AgentState\) -> dict:/.test(code1))
check('带节点标记注释', code1.includes('# 节点：'))
console.log('    首行:', code1.split('\n')[0].slice(0, 50))
await page.screenshot({ path: path.join(SHOTS, '01-new-node-code.png') })

console.log('\n[B] 保存后与 agent.py 一致')
await page.evaluate(() => {
  const b = [...document.querySelectorAll('.topbar button')].find((e) =>
    e.textContent.includes('保存'),
  )
  b && b.click()
})
await page.waitForFunction(
  () => [...document.querySelectorAll('.toast')].some((t) => t.textContent.includes('已保存')),
  { timeout: 30000, polling: 300 },
).catch(() => {})
await sleep(1200)
const code2 = await openCodeOfLastNode()
check('保存后代码没被换回旧模板', !code2.includes('runtime_sdk'))
check('保存后仍是原生块', /def \w+\(state: AgentState\)/.test(code2))
// 新增时用的是示例函数名，保存后后端会规范成节点实际名字，这里校验它确实对上了
// 块内部的函数名要和注释里写的节点标识一致（保存后后端会规范成实际名字）
const fnMatch = code2.match(/def (\w+)\(state: AgentState\)/)
const nameMatch = code2.match(/# 节点：.*?\((\w+)\)/)
check(
  '函数名与节点标识一致',
  !!fnMatch && !!nameMatch && fnMatch[1] === nameMatch[1],
  `函数 ${fnMatch?.[1]} / 标识 ${nameMatch?.[1]}`,
)

check('无 JS 运行时错误', errors.length === 0, errors.slice(0, 2).join(' ;; '))

await browser.close()
console.log(`\n${fail === 0 ? '全部通过 ✅' : `${fail} 项失败 ❌`}   截图：${SHOTS}`)
await sleep(200)
process.exitCode = fail === 0 ? 0 : 1
