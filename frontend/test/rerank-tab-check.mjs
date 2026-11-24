import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import puppeteer from 'puppeteer-core'

const BASE = 'http://127.0.0.1:8000'
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const SHOTS = path.join(os.tmpdir(), 'mineagent-rerank')
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

await page.evaluate(() => {
  const b = [...document.querySelectorAll('button')].find((x) =>
    x.textContent.replace(/\s+/g, '').includes('画布配置'))
  b && b.click()
})
await page.waitForSelector('.modal .tabs', { timeout: 10000 })
await sleep(500)

const tabs = await page.$$eval('.modal .tabs .tab', (els) =>
  els.map((e) => e.textContent.trim()))
console.log('  页签：' + tabs.join(' / '))
check('页签里有对话模型 / 重排模型',
  tabs.includes('对话模型') && tabs.includes('重排模型'), tabs.join(' | '))
check('向量模型已改名「向量检索模型」',
  tabs.includes('向量检索模型') && !tabs.includes('向量模型'), tabs.join(' | '))
await page.screenshot({ path: path.join(SHOTS, '01-tabs.png') })

// 切到向量检索模型页签：面板标题也要跟着改名，不能还是「向量模型」
await page.evaluate(() => {
  const t = [...document.querySelectorAll('.modal .tabs .tab')].find((e) =>
    e.textContent.includes('向量检索模型'))
  t && t.click()
})
await sleep(900)
const embTitle = await page.$eval('.modal .providers-title', (e) => e.textContent.trim())
  .catch(() => '')
check('面板标题同步改名', embTitle === '向量检索模型', embTitle)
await page.screenshot({ path: path.join(SHOTS, '01b-embedding-tab.png') })

await page.evaluate(() => {
  const t = [...document.querySelectorAll('.modal .tabs .tab')].find((e) =>
    e.textContent.includes('重排模型'))
  t && t.click()
})
await sleep(1200)
const body = await page.$eval('.modal', (e) => e.innerText)
check('切到重排页签有内容', body.includes('重排'), body.slice(0, 120).replace(/\n/g, ' | '))
await page.screenshot({ path: path.join(SHOTS, '02-rerank-tab.png') })

// 打开「新建」看厂商下拉是不是真的来自后端目录
const opened = await page.evaluate(() => {
  const b = [...document.querySelectorAll('.modal button')].find((x) =>
    /新建|添加|新增/.test(x.textContent))
  if (!b) return false
  b.click()
  return true
})
if (opened) {
  await sleep(800)
  const opts = await page.$$eval('.modal select option', (els) =>
    els.map((e) => e.textContent.trim()))
  console.log('  下拉候选：' + opts.slice(0, 6).join(' / '))
  check('厂商下拉有 Cohere / Jina / 硅基流动',
    opts.some((o) => o.includes('Cohere')) && opts.some((o) => o.includes('Jina'))
    && opts.some((o) => o.includes('硅基流动')), opts.join(' | ').slice(0, 200))
  await page.screenshot({ path: path.join(SHOTS, '03-new-rerank.png') })
  // 选中硅基流动，确认表单渲染出模型 / 条数 / Key
  await page.evaluate(() => {
    const s = [...document.querySelectorAll('.modal select')].find((e) =>
      [...e.options].some((o) => o.textContent.includes('硅基流动')))
    if (!s) return
    const opt = [...s.options].find((o) => o.textContent.includes('硅基流动'))
    s.value = opt.value
    s.dispatchEvent(new Event('change', { bubbles: true }))
  })
  await sleep(700)
  const form = await page.$eval('.modal', (e) => e.innerText)
  check('表单渲染出模型名与 API Key',
    form.includes('模型名') && form.includes('API Key') && form.includes('Base URL'),
    form.slice(0, 200).replace(/\n/g, ' | '))
  await page.screenshot({ path: path.join(SHOTS, '04-rerank-form.png') })
} else {
  check('重排页签有「新建」入口', false, body.slice(0, 200))
}

check('没有前端报错', errors.length === 0, errors.slice(0, 3).join(' | '))
console.log(`\n结果：${pass} 通过 / ${fail} 失败`)
await browser.close()
process.exit(fail ? 1 : 0)
