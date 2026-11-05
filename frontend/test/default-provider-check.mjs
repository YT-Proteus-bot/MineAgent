import puppeteer from 'puppeteer-core'
import path from 'node:path'
import os from 'node:os'
import fs from 'node:fs'

const BASE = 'http://127.0.0.1:8000'
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const SHOTS = path.join(os.tmpdir(), 'mineagent-defaults')
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

const readModal = async () => {
  await page.waitForSelector('.modal', { timeout: 6000 })
  await sleep(900)
  return page.evaluate(() => {
    const sel = document.querySelector('.modal select')
    const inputs = [...document.querySelectorAll('.modal input')].map((e) => e.value)
    return {
      provider: sel ? sel.options[sel.selectedIndex]?.textContent?.trim() : '',
      providerValue: sel ? sel.value : '',
      values: inputs.slice(0, 3),
    }
  })
}

console.log('\n[A] 用户中心默认 DeepSeek')
await page.evaluate(() => {
  const b = [...document.querySelectorAll('.topbar button')].find((x) =>
    x.textContent.includes('用户中心'),
  )
  b && b.click()
})
const uc = await readModal()
check('服务商默认 DeepSeek', /DeepSeek/i.test(uc.provider), uc.provider)
check('服务商下拉第一项是 DeepSeek', uc.providerValue === 'deepseek', uc.providerValue)
check('Base URL 指向 deepseek', (uc.values[1] || '').includes('deepseek'), uc.values[1])
console.log('    模型名:', uc.values[2])
await page.screenshot({ path: path.join(SHOTS, '01-user-center.png') })
await page.keyboard.press('Escape')
await sleep(500)

console.log('\n[B] 画布模型弹窗默认 DeepSeek')
await page.evaluate(() => {
  const b = [...document.querySelectorAll('.topbar button')].find(
    (x) => x.textContent.includes('模型') && !x.textContent.includes('用户'),
  )
  b && b.click()
})
const cm = await readModal()
check('画布弹窗服务商也是 DeepSeek', /DeepSeek/i.test(cm.provider), cm.provider)
await page.screenshot({ path: path.join(SHOTS, '02-canvas-model.png') })
await page.keyboard.press('Escape')
await sleep(400)

console.log('\n[C] 节点模型弹窗默认 DeepSeek')
await page.evaluate(() => {
  const el = [...document.querySelectorAll('.agent-node')].find(
    (n) => n.querySelector('.node-kind')?.textContent === 'agent',
  )
  el?.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, clientX: 800, clientY: 500 }))
})
await page.waitForSelector('.ctx-menu', { timeout: 6000 })
await page.evaluate(() => {
  const el = [...document.querySelectorAll('.ctx-menu .ctx-item')].find((e) =>
    e.textContent.includes('配置模型'),
  )
  el?.click()
})
const nm = await readModal()
check('节点弹窗服务商也是 DeepSeek', /DeepSeek/i.test(nm.provider), nm.provider)

check('无 JS 运行时错误', errors.length === 0, errors.slice(0, 2).join(' ;; '))

await browser.close()
console.log(`\n${fail === 0 ? '全部通过 ✅' : `${fail} 项失败 ❌`}   截图：${SHOTS}`)
await sleep(200)
process.exitCode = fail === 0 ? 0 : 1
