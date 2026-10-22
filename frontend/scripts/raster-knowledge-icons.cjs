// Keep the prototype's vector paths; emit native-compatible PNGs in its exact colours.
const fs = require('node:fs')
const path = require('node:path')
const { chromium } = require('@playwright/test')
;(async () => {
  const output = path.resolve('src/assets/knowledge-icons')
  fs.mkdirSync(output, { recursive: true })
  const browser = await chromium.launch({ channel: 'chrome', headless: true })
  const page = await browser.newPage()
  const icons = [['folder', 'blue', '#336ae8'], ['file', 'blue', '#336ae8'], ['upload', 'blue', '#336ae8'], ['link', 'blue', '#336ae8'], ['eye', 'blue', '#336ae8'], ['plus', 'blue', '#336ae8'], ['plus', 'white', '#ffffff'], ['chevron', 'muted', '#a0aec3'], ['trash', 'red', '#ce554d']]
  try {
    for (const [name, tone, colour] of icons) {
      const source = fs.readFileSync(path.resolve('src/assets/icons', name + '.svg'), 'utf8').replaceAll('#202a3d', colour)
      const png = await page.evaluate(async svg => {
        const image = new Image(); image.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg); await image.decode()
        const canvas = document.createElement('canvas'); canvas.width = 48; canvas.height = 48
        canvas.getContext('2d').drawImage(image, 0, 0, 48, 48)
        return canvas.toDataURL('image/png').split(',')[1]
      }, source)
      fs.writeFileSync(path.join(output, `${name}-${tone}.png`), Buffer.from(png, 'base64'))
    }
  } finally { await browser.close() }
  console.log('Generated 9 knowledge-library icon variants from the existing SVG paths.')
})().catch(error => { console.error(error); process.exit(1) })
