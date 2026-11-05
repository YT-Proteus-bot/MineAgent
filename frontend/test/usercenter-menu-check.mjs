import puppeteer from 'puppeteer-core'
import path from 'node:path'
import os from 'node:os'
import fs from 'node:fs'

const BASE = 'http://127.0.0.1:8000'
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const SHOTS = path.join(os.tmpdir(), 'mineagent-usercenter')
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

const openUserMenu = async () => {
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('.topbar button')].find((x) =>
      x.textContent.includes('用户中心'),
    )
    b && b.click()
  })
  await sleep(600)
}

console.log('\n[A] 用户中心变成下拉，三项齐全')
await openUserMenu()
const items = await page.$$eval('.popover .menu-item', (els) =>
  els.map((e) => e.textContent.replace(/\s+/g, ' ').trim()),
).catch(() => [])
check('有 GitHub 账户', items.some((t) => t.includes('GitHub 账户')), items.join(' | '))
check('有模型配置', items.some((t) => t.includes('模型配置')))
check('有公共模板', items.some((t) => t.includes('公共模板')))
check('三项都在', items.length === 3, `${items.length} 项`)
await page.screenshot({ path: path.join(SHOTS, '01-dropdown.png') })

console.log('\n[B] GitHub 账户窗口')
await page.evaluate(() => {
  const el = [...document.querySelectorAll('.popover .menu-item')].find((e) =>
    e.textContent.includes('GitHub 账户'),
  )
  el?.click()
})
await page.waitForSelector('.modal', { timeout: 8000 })
await sleep(1000)
const ghText = await page.$eval('.modal', (el) => el.textContent)
check('窗口标题是 GitHub 账户', /GitHub 账户/.test(ghText))
check('显示连接状态', /未连接|已连接/.test(ghText))
// 已连接时按钮是「断开连接」，未连接时是「连接 GitHub」
check('有连接/断开按钮', /连接 GitHub|断开连接/.test(ghText), ghText.includes('已连接') ? '已连接状态（断开连接）' : '未连接状态（连接 GitHub）')
check('有 OAuth 设置入口', /OAuth|展开/.test(ghText))
await page.screenshot({ path: path.join(SHOTS, '02-github.png') })

// 展开高级设置
await page.evaluate(() => {
  const b = [...document.querySelectorAll('.modal button')].find((e) =>
    e.textContent.includes('OAuth') || e.textContent.includes('展开'),
  )
  b && b.click()
})
await sleep(600)
const advText = await page.$eval('.modal', (el) => el.textContent)
check('展开后有 Client ID / 仓库字段', /Client ID/.test(advText) && /模板仓库/.test(advText))
check('显示回调地址', /callback/.test(advText))
await page.screenshot({ path: path.join(SHOTS, '03-oauth.png') })
await page.keyboard.press('Escape')
await sleep(500)

console.log('\n[C] 模型配置仍能打开')
await openUserMenu()
await page.evaluate(() => {
  const el = [...document.querySelectorAll('.popover .menu-item')].find((e) =>
    e.textContent.includes('模型配置'),
  )
  el?.click()
})
await page.waitForSelector('.modal', { timeout: 8000 })
await sleep(800)
const modelText = await page.$eval('.modal', (el) => el.textContent)
check('打开的是模型配置窗口', /服务商|Base URL|模型名/.test(modelText))
await page.keyboard.press('Escape')
await sleep(400)

console.log('\n[D] 公共模板仍能打开')
await openUserMenu()
await page.evaluate(() => {
  const el = [...document.querySelectorAll('.popover .menu-item')].find((e) =>
    e.textContent.includes('公共模板'),
  )
  el?.click()
})
await page.waitForSelector('.modal', { timeout: 8000 })
await sleep(1200)
const communityText = await page.$eval('.modal', (el) => el.textContent)
check('打开的是公共模板窗口', /社区|模板/.test(communityText))
await page.screenshot({ path: path.join(SHOTS, '04-community.png') })

check('无 JS 运行时错误', errors.length === 0, errors.slice(0, 2).join(' ;; '))

await browser.close()
console.log(`\n${fail === 0 ? '全部通过 ✅' : `${fail} 项失败 ❌`}   截图：${SHOTS}`)
await sleep(200)
process.exitCode = fail === 0 ? 0 : 1
