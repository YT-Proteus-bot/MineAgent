import puppeteer from 'puppeteer-core'
import path from 'node:path'
import os from 'node:os'
import fs from 'node:fs'

const BASE = 'http://127.0.0.1:8000'
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const SHOTS = path.join(os.tmpdir(), 'mineagent-assistant')
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

const activeTab = () =>
  page.$eval('.pane-tab.active', (el) => el.textContent.trim()).catch(() => '(无)')

console.log('\n[A] 右列 tab 与默认面板')
check('有「AI 助手」tab', await page.$eval('.pane-tabs', (el) => el.textContent.includes('AI 助手')))
check('默认停在 AI 助手', (await activeTab()).includes('AI 助手'), await activeTab())
check('助手输入框存在', !!(await page.$('.chat-input textarea')))

console.log('\n[B] hover 节点显示信息浮层')
const box = await (await page.$$('.agent-node'))[2].boundingBox()
await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
await sleep(600)
const tip = await page.$('.node-tip')
check('出现悬停浮层', !!tip)
if (tip) {
  const text = await page.$eval('.node-tip', (el) => el.textContent)
  check('浮层里有节点类型', /类型/.test(text), text.slice(0, 60).replace(/\s+/g, ' '))
}
await page.screenshot({ path: path.join(SHOTS, '01-hover-tip.png') })

console.log('\n[C] 单击节点不再打开右侧详情')
await (await page.$$('.agent-node'))[2].click()
await sleep(700)
check('单击后仍停在助手', (await activeTab()).includes('AI 助手'), await activeTab())
check('右列没有渲染节点详情', !(await page.$('.inspector')))

console.log('\n[D] 右键节点 -> 切到节点详情')
await (await page.$$('.agent-node'))[2].click({ button: 'right' })
await page.waitForSelector('.ctx-menu', { timeout: 6000 })
await sleep(400)
check('右键后自动切到节点详情', (await activeTab()).includes('节点详情'), await activeTab())
check('详情面板已渲染', !!(await page.$('.inspector')))
await page.screenshot({ path: path.join(SHOTS, '02-node-detail.png') })
await page.keyboard.press('Escape')
await sleep(300)

console.log('\n[E] 助手对话')
await page.evaluate(() => {
  const t = [...document.querySelectorAll('.pane-tab')].find((e) => e.textContent.includes('AI 助手'))
  t && t.click()
})
await sleep(400)
await page.click('.chat-input textarea')
await page.keyboard.type('ReAct 和 Plan-and-Execute 该怎么选？', { delay: 5 })
await page.keyboard.press('Enter')
await page.waitForFunction(
  () => {
    const els = [...document.querySelectorAll('.chat-msg.assistant')]
    const last = els[els.length - 1]
    return last && last.textContent.trim().length > 4 && !last.textContent.includes('思考中')
  },
  { timeout: 60000, polling: 300 },
)
const reply = await page.evaluate(() => {
  const els = [...document.querySelectorAll('.chat-msg.assistant')]
  return els[els.length - 1]?.textContent || ''
})
check('助手返回了回复', reply.trim().length > 4, reply.slice(0, 60).replace(/\s+/g, ' '))
check('用户消息在列表里', (await page.$eval('.chat-list', (el) => el.textContent)).includes('Plan-and-Execute'))
await sleep(500)
await page.screenshot({ path: path.join(SHOTS, '03-assistant-chat.png') })

check('无 JS 运行时错误', errors.length === 0, errors.slice(0, 2).join(' ;; '))

await browser.close()
console.log(`\n${fail === 0 ? '全部通过 ✅' : `${fail} 项失败 ❌`}   截图：${SHOTS}`)
await sleep(200)
process.exitCode = fail === 0 ? 0 : 1
