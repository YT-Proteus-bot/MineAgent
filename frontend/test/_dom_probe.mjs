import puppeteer from 'puppeteer-core'

const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: 'new',
  args: ['--no-sandbox', '--disable-gpu', '--window-size=1680,1000'],
})
const page = await browser.newPage()
await page.setViewport({ width: 1680, height: 1000 })
await page.goto('http://127.0.0.1:8000', { waitUntil: 'networkidle2', timeout: 40000 })
await page.waitForSelector('.agent-node', { timeout: 25000 })
await sleep(1500)

const box = await page.evaluate(() => {
  const el = document.querySelector('.react-flow__pane')
  const r = el.getBoundingClientRect()
  return { x: r.x + 60, y: r.y + r.height - 120 }
})
await page.mouse.click(box.x, box.y, { button: 'right' })
await page.waitForSelector('.ctx-menu', { timeout: 6000 })
await sleep(400)
await page.evaluate(() => {
  const el = [...document.querySelectorAll('.ctx-menu .ctx-item')].find((e) =>
    e.textContent.includes('添加节点'),
  )
  el && el.click()
})
await sleep(1000)

const info = await page.evaluate(() => {
  const inp = document.querySelector('input[placeholder*="搜索节点"]')
  const chain = []
  let n = inp
  for (let i = 0; i < 6 && n; i++) {
    chain.push(`${n.tagName}.${(n.className || '').toString().split(' ')[0]}`)
    n = n.parentElement
  }
  const root = inp ? inp.closest('div[class]')?.parentElement : null
  // 找一个包含多个"节点行"的容器
  const candidates = [...document.querySelectorAll('div')]
    .filter((d) => d.children.length > 8 && d.className)
    .slice(0, 4)
    .map((d) => ({
      cls: d.className.toString().slice(0, 40),
      kids: d.children.length,
      firstKid: d.children[0]?.className?.toString().slice(0, 40),
    }))
  return { inputClass: inp?.className, chain, rootCls: root?.className, candidates }
})
console.log(JSON.stringify(info, null, 2))
await browser.close()
