import puppeteer from 'puppeteer-core'
import path from 'node:path'
import os from 'node:os'
import fs from 'node:fs'

const BASE = 'http://127.0.0.1:8000'
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const SHOTS = path.join(os.tmpdir(), 'mineagent-native-code')
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

console.log('\n[A] 节点代码页显示 agent.py 里的原生函数')
await page.evaluate(() => {
  const list = [...document.querySelectorAll('.agent-node')]
  const idx = list.findIndex((n) => n.querySelector('.node-kind')?.textContent === 'agent')
  list[idx]?.dispatchEvent(
    new MouseEvent('contextmenu', { bubbles: true, clientX: 800, clientY: 500 }),
  )
})
await page.waitForSelector('.ctx-menu', { timeout: 6000 })
await page.evaluate(() => {
  const el = [...document.querySelectorAll('.ctx-menu .ctx-item')].find((e) =>
    e.textContent.includes('编辑代码'),
  )
  el && el.click()
})
await sleep(1200)

const code = await page.evaluate(() => {
  const ta = document.querySelector('.inspector textarea')
  return ta ? ta.value : ''
})
check('代码编辑器已打开', code.length > 0, `${code.length} 字符`)
check('内容是 agent.py 里的函数', /def \w+\(state: AgentState\) -> dict:/.test(code))
check('包含 create_agent 调用', code.includes('create_agent'))
check('包含节点标记注释', code.includes('# 节点：'))
console.log('    开头:', code.split('\n').slice(0, 3).join(' / '))
await page.screenshot({ path: path.join(SHOTS, '01-node-code.png') })

console.log('\n[B] 运行面板显示真实运行模式')
await page.evaluate(() => {
  const b = [...document.querySelectorAll('.topbar button')].find((e) =>
    e.textContent.includes('运行'),
  )
  b && b.click()
})
await sleep(800)
// 填任务并点「开始运行」
await page.evaluate(() => {
  const ta = [...document.querySelectorAll('textarea')].find((e) =>
    (e.getAttribute('placeholder') || '').includes('会传给 input'),
  )
  if (ta) {
    const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set
    setter.call(ta, '截图用的一次运行')
    ta.dispatchEvent(new Event('input', { bubbles: true }))
  }
})
await sleep(300)
await page.evaluate(() => {
  const b = [...document.querySelectorAll('button')].find((e) =>
    e.textContent.includes('开始运行'),
  )
  b && b.click()
})
await page.waitForFunction(
  () => [...document.querySelectorAll('.evt')].some((e) => e.textContent.includes('准备')),
  { timeout: 90000, polling: 400 },
).catch(() => {})
await page.waitForFunction(
  () => [...document.querySelectorAll('.evt')].some((e) => e.textContent.includes('结束')),
  { timeout: 90000, polling: 400 },
).catch(() => {})
await sleep(1200)
const eventsText = await page.$eval('.run-panel, .panel', (el) => el.textContent).catch(() => '')
check('运行面板标注了真实运行', /真实运行/.test(eventsText), eventsText.slice(0, 100).replace(/\s+/g, ' '))
// 真实模型可能跑得比较久，这里只要求已经开跑（结束状态由 API 层的测试覆盖）
check('运行已经启动', /正在执行|结束|运行中/.test(eventsText))
await page.screenshot({ path: path.join(SHOTS, '02-run.png') })

check('无 JS 运行时错误', errors.length === 0, errors.slice(0, 2).join(' ;; '))

await browser.close()
console.log(`\n${fail === 0 ? '全部通过 ✅' : `${fail} 项失败 ❌`}   截图：${SHOTS}`)
await sleep(200)
process.exitCode = fail === 0 ? 0 : 1
