import puppeteer from 'puppeteer-core'
import path from 'node:path'
import os from 'node:os'
import fs from 'node:fs'

const BASE = 'http://127.0.0.1:8000'
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const SHOTS = path.join(os.tmpdir(), 'mineagent-restore-canvas')
fs.mkdirSync(SHOTS, { recursive: true })
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

let pass = 0
let fail = 0
const check = (n, ok, extra = '') => {
  console.log(`  ${ok ? '✔' : '✘'} ${n}${extra ? ` — ${extra}` : ''}`)
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

await page.goto(BASE, { waitUntil: 'networkidle2', timeout: 40000 })
await page.waitForSelector('.agent-node', { timeout: 25000 })
await sleep(2200)

// 当前画布
const first = await page.evaluate(() => {
  const el = document.querySelector('.topbar .name, .topbar button span')
  return {
    name: document.querySelector('.topbar button span')?.textContent?.trim() || '',
    url: window.location.href,
  }
})
console.log(`\n初始画布: ${first.name}`)
console.log(`初始 URL: ${first.url}`)

// 从下拉里切到另一张画布（第 3 项，避开第一张）
await page.evaluate(() => {
  const b = [...document.querySelectorAll('.topbar button')].find((x) =>
    x.textContent.includes('选择画布') || x.querySelector('.dim.small'),
  )
  b && b.click()
})
await sleep(700)
const picked = await page.evaluate(() => {
  const items = [...document.querySelectorAll('.menu-scroll .menu-item')]
  if (items.length < 3) return null
  const t = items[2].textContent.replace(/\s+/g, ' ').trim()
  items[2].click()
  return t
})
await sleep(2500)
check('切换到了另一张画布', !!picked, picked || '')

const afterSwitch = await page.evaluate(() => ({
  name: document.querySelector('.topbar button span')?.textContent?.trim() || '',
  url: window.location.href,
  stored: (() => {
    try {
      return localStorage.getItem('mineagent:canvas') || ''
    } catch {
      return ''
    }
  })(),
}))
console.log(`\n切换后: ${afterSwitch.name}`)
console.log(`URL: ${afterSwitch.url}`)
check('URL 带上 canvas 参数', afterSwitch.url.includes('canvas='), afterSwitch.url.split('?')[1]?.slice(0, 60) || '')
check('localStorage 记住了画布', !!afterSwitch.stored, afterSwitch.stored.slice(0, 12))

// 刷新页面
await page.reload({ waitUntil: 'networkidle2' })
await page.waitForSelector('.agent-node', { timeout: 25000 })
await sleep(2500)

const afterReload = await page.evaluate(() => ({
  name: document.querySelector('.topbar button span')?.textContent?.trim() || '',
  stored: (() => {
    try {
      return localStorage.getItem('mineagent:canvas') || ''
    } catch {
      return ''
    }
  })(),
}))
console.log(`\n刷新后: ${afterReload.name}`)

check('刷新后停在切换过的画布', afterReload.name === afterSwitch.name,
  `${afterSwitch.name} → ${afterReload.name}`)
check('刷新后没有回到第一张', afterReload.name !== first.name || first.name === afterSwitch.name)

await page.screenshot({ path: path.join(SHOTS, '01-after-reload.png') })

// 直接访问带 canvas 参数的 URL，也应落到同一张
const targetId = afterReload.stored
await page.goto(`${BASE}/?canvas=${targetId}`, { waitUntil: 'networkidle2' })
await page.waitForSelector('.agent-node', { timeout: 25000 })
await sleep(2200)
const viaUrl = await page.evaluate(() => ({
  name: document.querySelector('.topbar button span')?.textContent?.trim() || '',
}))
check('带 canvas 参数的 URL 直接打开同一张', viaUrl.name === afterSwitch.name,
  `${viaUrl.name}`)

check('无 JS 错误', errors.length === 0, errors.slice(0, 2).join(' ;; '))

await browser.close()
console.log(`\n${fail === 0 ? '全部通过 ✅' : `${fail} 项失败 ❌`}   截图：${SHOTS}`)
await sleep(150)
process.exitCode = fail === 0 ? 0 : 1
