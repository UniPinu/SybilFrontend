/**
 * End-to-end check of live mode: pick a person nobody has run, let the backend
 * download the scan from Imaging Data Commons and run the real ensemble, and
 * follow the SSE stream the whole way.
 *
 *   node live-check.mjs            # against http://127.0.0.1:8000
 *   BASE=http://localhost:5173 node live-check.mjs   # through the vite proxy
 *
 * Takes a few minutes: it is a real download and a real inference.
 */
import { chromium } from 'playwright'

const BASE = process.env.BASE ?? 'http://127.0.0.1:8000'
const OUT = process.env.OUT ?? '.'
const DEADLINE_MS = Number(process.env.DEADLINE_MS ?? 420_000)

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
const errors = []
const stages = new Set()
page.on('console', (m) => m.type() === 'error' && errors.push(m.text()))
page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`))

await page.goto(BASE, { waitUntil: 'networkidle' })
await page.getByLabel(/Live mode/i).click()
await page.getByRole('button', { name: /Pick a random person/i }).click()
await page.waitForSelector('#run', { timeout: 30_000 })

const person = new URL(page.url()).searchParams.get('p')
console.log(`live person: ${person}`)

await page.getByRole('button', { name: /^Run Sybil$/i }).click()

const started = Date.now()
let shotTaken = false
while (Date.now() - started < DEADLINE_MS) {
  const text = await page.locator('#run').innerText()
  for (const stage of ['Fetching the scan', 'Reading the scan', 'Making every scan look alike',
                       '5 experts vote', 'Turning votes', 'Preparing the pictures']) {
    if (text.includes(stage)) stages.add(stage)
  }
  const experts = text.match(/expert (\d) of 5/)
  if (experts && !shotTaken && Number(experts[1]) >= 2) {
    await page.screenshot({ path: `${OUT}/live-01-progress.png` })
    shotTaken = true
    console.log(`progress: expert ${experts[1]} of 5 at ${Math.round((Date.now() - started) / 1000)}s`)
  }
  if (await page.locator('#prediction').count() && text.includes('Run Sybil') === false) {
    // the button text flips back when the run is finished
  }
  const done = await page.getByText(/6-year risk/i).count()
  if (done) break
  if (text.includes('Try again')) {
    console.error('run failed:', text)
    break
  }
  await page.waitForTimeout(2000)
}

const seconds = Math.round((Date.now() - started) / 1000)
await page.locator('#prediction').scrollIntoViewIfNeeded()
await page.waitForTimeout(1500)
await page.screenshot({ path: `${OUT}/live-02-result.png` })

const headline = await page.locator('#prediction').innerText().catch(() => '')
await page.getByRole('button', { name: /Reveal what happened/i }).click()
await page.waitForTimeout(1200)
await page.locator('#reveal').scrollIntoViewIfNeeded()
await page.screenshot({ path: `${OUT}/live-03-reveal.png` })
const reveal = await page
  .locator('#reveal .flip-face-back')
  .innerText()
  .catch(() => '(the card did not flip)')

console.log(JSON.stringify({
  person,
  seconds,
  stagesSeen: [...stages],
  headline: headline.split('\n').slice(0, 6),
  reveal: reveal.split('\n').slice(0, 6),
  errors,
}, null, 2))

await browser.close()
