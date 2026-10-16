// Image props cross the mini program bridge. Keep imported PNGs as file paths.
const fs = require('node:fs')
const path = require('node:path')
const assert = require('node:assert/strict')

const root = path.resolve(__dirname, '../dist')
function files(directory) {
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap(entry => {
    const file = path.join(directory, entry.name)
    return entry.isDirectory() ? files(file) : [file]
  })
}
const scripts = files(root).filter(file => file.endsWith('.js'))
assert(scripts.length, 'Build the mini program before checking assets')
let inlineImages = 0, jsBytes = 0
for (const file of scripts) {
  const code = fs.readFileSync(file, 'utf8')
  jsBytes += Buffer.byteLength(code)
  inlineImages += (code.match(/data:image\/[a-z0-9.+-]+;base64,/gi) || []).length
}
assert.equal(inlineImages, 0, `${inlineImages} base64 images remain in the mini program JavaScript`)
const source = path.resolve(__dirname, '../src/assets')
const images = files(source).filter(file => file.endsWith('.png'))
for (const file of images) {
  const emitted = path.join(root, 'assets', path.relative(source, file))
  assert(fs.existsSync(emitted), `Missing image: ${path.relative(root, emitted)}`)
  assert.equal(fs.statSync(emitted).size, fs.statSync(file).size, `Changed image: ${emitted}`)
}
console.log(JSON.stringify({ passed: true, images: images.length, inlineImages, jsBytes }))
