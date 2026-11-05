/**
 * 前端交互冒烟测试（headless Chrome + puppeteer-core）。
 *
 * 用法（服务已启动，且 mock 模型在 8012）：
 *   cd frontend
 *   node test/ui-smoke.mjs
 */
import puppeteer from 'puppeteer-core'
import path from 'node:path'
import fs from 'node:fs'
import os from 'node:os'

const BASE = process.env.BASE_URL || 'http://127.0.0.1:8000'
const MOCK = process.env.MOCK_URL || 'http://127.0.0.1:8012/v1'
const CHROME =
  process.env.CHROME_PATH ||
  'C:/Program Files/Google/Chrome/Application/chrome.exe'
const SHOTS = process.env.SHOT_DIR || path.join(os.tmpdir(), 'mineagent-shots')
fs.mkdirSync(SHOTS, { recursive: true })

let failures = 0
const check = (name, ok, extra = '') => {
  console.log(`  ${ok ? '✔' : '✘'} ${name}${extra ? ` — ${extra}` : ''}`)
  if (!ok) failures++
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

// 让运行时指向 mock 模型，这样不需要真 key
await fetch(`${BASE}/api/settings`, {
  method: 'PUT',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    orchestrator_provider: 'openai',
    orchestrator_base_url: MOCK,
    orchestrator_model: 'mock-model',
    orchestrator_api_key: 'mock-key',
  }),
})

// 建一个专用画布，测完删掉，不动用户数据
const createdCanvas = await (
  await fetch(`${BASE}/api/canvases`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: `UI 冒烟测试 ${Date.now() % 100000}`, framework: 'langchain' }),
  })
).json()
console.log(`  · 已创建测试画布 ${createdCanvas.name}`)

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: 'new',
  args: ['--no-sandbox', '--disable-gpu', '--window-size=1680,1000', '--force-device-scale-factor=1'],
})
const page = await browser.newPage()
await page.setViewport({ width: 1680, height: 1000 })

const errors = []
page.on('pageerror', (e) => errors.push('pageerror: ' + e.message))
page.on('console', (m) => {
  if (m.type() === 'error') errors.push('console: ' + m.text().slice(0, 200))
})

console.log('\n[1] 页面加载与画布切换')
try {
  await page.goto(BASE, { waitUntil: 'networkidle2', timeout: 40000 })
  await page.waitForSelector('.agent-node', { timeout: 25000 })

  // 通过左上角下拉切换到刚建的测试画布
  await page.evaluate(() => document.querySelector('.topbar .popover-root button').click())
  await page.waitForSelector('.popover .menu-item', { timeout: 5000 })
  await page.screenshot({ path: path.join(SHOTS, '00-canvas-switcher.png') })
  await page.evaluate((name) => {
    const el = [...document.querySelectorAll('.popover .menu-item')].find((e) =>
      e.textContent.includes(name),
    )
    el && el.click()
  }, createdCanvas.name)
  await sleep(900)

  const n0 = await page.$$eval('.agent-node', (els) => els.length)
  check('画布渲染出节点', n0 > 0, `${n0} 个节点`)
  const title = await page.$eval('.topbar .popover-root button', (el) => el.textContent.trim())
  check('画布切换生效', title.includes(createdCanvas.name.replace(/\d+$/, '')), title.slice(0, 40))
  const buttons = await page.$$eval('.topbar button', (els) => els.map((e) => e.textContent.trim()))
  check('顶部栏按钮齐全', buttons.some((b) => b.includes('运行')) && buttons.some((b) => b.includes('用户中心')), buttons.join(' | '))
} catch (e) {
  check('页面加载', false, String(e).slice(0, 200))
}

console.log('\n[2] 右键画布新增节点')
let pickerCount = 0
const n0Before = await page.$$eval('.agent-node', (els) => els.length)
try {
  await page.mouse.click(520, 800, { button: 'right' })
  await page.waitForSelector('.ctx-search input', { timeout: 6000 })
  pickerCount = await page.$$eval('.ctx-item', (els) => els.length)
  check('弹出节点选择器', pickerCount > 40, `${pickerCount} 个节点类型`)
  await page.screenshot({ path: path.join(SHOTS, '01-node-picker.png') })

  await page.type('.ctx-search input', 'observ', { delay: 15 })
  await sleep(350)
  const filtered = await page.$$eval('.ctx-item', (els) => els.map((e) => e.textContent.trim()))
  check('搜索过滤生效', filtered.length > 0 && filtered.length < pickerCount, filtered.slice(0, 3).join(' / '))
  await page.screenshot({ path: path.join(SHOTS, '02-search.png') })

  await page.click('.ctx-item')
  await sleep(500)
  const n1 = await page.$$eval('.agent-node', (els) => els.length)
  check('画布上新增了节点', n1 === n0Before + 1, `${n0Before} → ${n1}`)
} catch (e) {
  check('右键新增节点', false, String(e).slice(0, 200))
}

console.log('\n[3] 右键节点编辑代码')
try {
  const handles = await page.$$('.agent-node')
  let target = null
  for (const h of handles) {
    const b = await h.boundingBox()
    if (b && b.x > 40 && b.y > 90 && b.x < 1300 && b.y < 880) {
      target = h
      break
    }
  }
  check('找到可见节点', !!target, `${handles.length} 个节点`)
  await target.click({ button: 'right' })
  await page.waitForSelector('.ctx-menu', { timeout: 6000 })
  const menuText = await page.$$eval('.ctx-menu .ctx-item', (els) => els.map((e) => e.textContent.trim()))
  check('节点右键菜单', menuText.some((t) => t.includes('编辑代码')), menuText.join(' | '))
  await page.screenshot({ path: path.join(SHOTS, '03-node-menu.png') })

  await page.evaluate(() => {
    const el = [...document.querySelectorAll('.ctx-menu .ctx-item')].find((e) =>
      e.textContent.includes('编辑代码'),
    )
    el && el.click()
  })
  await page.waitForSelector('textarea.code-area', { timeout: 6000 })
  const code = await page.$eval('textarea.code-area', (el) => el.value)
  check('代码编辑器载入默认模板', code.includes('def run'), code.split('\n').slice(0, 2).join(' / ').slice(0, 80))
  await page.screenshot({ path: path.join(SHOTS, '04-code-editor.png') })

  // 粘贴一段新代码（模拟 Ctrl+V 后的内容替换）
  await page.focus('textarea.code-area')
  await page.keyboard.down('Control')
  await page.keyboard.press('KeyA')
  await page.keyboard.up('Control')
  await page.keyboard.type('def run(ctx):\n    return ctx.text + " [edited by test]"\n', { delay: 3 })
  const edited = await page.$eval('textarea.code-area', (el) => el.value)
  check('代码可编辑', edited.includes('edited by test'), `${edited.length} 字符`)
} catch (e) {
  check('节点代码编辑', false, String(e).slice(0, 200))
}

console.log('\n[4] 保存并落盘')
try {
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('.topbar button')].find((x) => x.textContent.includes('保存'))
    b && b.click()
  })
  await page.waitForFunction(
    () => [...document.querySelectorAll('.toast')].some((t) => t.textContent.includes('个文件写入')),
    { timeout: 25000 },
  )
  const toast = await page.$$eval('.toast', (els) => els.map((e) => e.textContent).join(' | '))
  check('保存成功并落盘', true, toast.slice(0, 80))
  const dirty = await page.$$eval('.badge', (els) => els.some((e) => e.textContent.includes('未保存')))
  check('保存后未保存标记消失', !dirty)
} catch (e) {
  check('保存并落盘', false, String(e).slice(0, 200))
}

console.log('\n[5] 运行智能体')
try {
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('.run-head button')].find((x) => x.textContent.includes('运行面板'))
    b && b.click()
  })
  await page.waitForSelector('.run-left textarea', { timeout: 6000 })
  await page.type('.run-left textarea', '为本地 Agent 编排平台写一份调研报告', { delay: 5 })
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('.run-left button')].find((x) => x.textContent.includes('开始运行'))
    b && b.click()
  })
  await page.waitForFunction(
    () => {
      const el = document.querySelector('.run-output')
      return el && el.textContent && el.textContent.trim().length > 10
    },
    { timeout: 120000, polling: 500 },
  )
  const out = await page.$eval('.run-output', (el) => el.textContent.trim())
  check('运行完成并拿到输出', out.length > 10, out.slice(0, 90).replace(/\s+/g, ' '))
  await page.screenshot({ path: path.join(SHOTS, '05-run-output.png') })

  await page.evaluate(() => {
    const t = [...document.querySelectorAll('.run-tabs .tab')].find((x) => x.textContent.includes('执行过程'))
    t && t.click()
  })
  await sleep(400)
  const evts = await page.$$eval('.evt', (els) => els.length)
  check('执行过程事件流', evts > 4, `${evts} 条事件`)
  await page.screenshot({ path: path.join(SHOTS, '06-run-events.png') })
} catch (e) {
  check('运行智能体', false, String(e).slice(0, 200))
  await page.screenshot({ path: path.join(SHOTS, '99-run-fail.png') }).catch(() => {})
}

console.log('\n[6] 运行时错误检查')
check('没有 JS 运行时错误', errors.length === 0, errors.slice(0, 3).join(' ;; '))

await browser.close()
await fetch(`${BASE}/api/canvases/${createdCanvas.id}`, { method: 'DELETE' }).catch(() => {})
console.log(`\n截图目录：${SHOTS}`)
console.log(failures === 0 ? '\n全部通过 ✅\n' : `\n${failures} 项失败 ❌\n`)
process.exit(failures === 0 ? 0 : 1)
