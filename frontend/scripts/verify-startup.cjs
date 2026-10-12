// Execute the generated App/page module graph and initial lifecycle in a small
// native API stub. This catches missing webpack factories; actual WeChat UI and
// authorization still require the developer tool or a device.
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const root = path.resolve(__dirname, '../dist')
const loaded = new Set()
let app, page
const windowInfo = { platform: 'devtools', windowWidth: 390, windowHeight: 812, statusBarHeight: 20 }
const wx = new Proxy({
  getSystemInfoSync: () => windowInfo,
  getWindowInfo: () => windowInfo,
  getAppBaseInfo: () => ({ SDKVersion: '3.17.4', theme: 'light' }),
  getDeviceInfo: () => ({ platform: 'devtools' }),
  getStorageSync: () => '',
  canIUse: () => true,
}, { get: (target, key) => key in target ? target[key] : typeof key === 'string' && key.startsWith('on') ? () => {} : undefined })
const context = vm.createContext({
  wx, console, setTimeout, clearTimeout, setInterval, clearInterval, Promise, Date, URL,
  App: value => { app = value }, Page: value => { page = value }, Component: () => {},
  getApp: () => app, getCurrentPages: () => [], Behavior: value => value,
})
context.global = context
context.globalThis = context
function load(file) {
  if (!file.endsWith('.js')) file += '.js'
  if (loaded.has(file)) return
  loaded.add(file)
  const code = fs.readFileSync(file, 'utf8')
  context.require = relative => load(path.resolve(path.dirname(file), relative))
  vm.runInContext(code, context, { filename: path.relative(root, file) })
}
try {
  load(path.join(root, 'app.js'))
  load(path.join(root, 'pages/index/index.js'))
  if (!app || !page) throw new Error('App or page was not registered')
  app.onLaunch?.({})
  const nativePage = {
    ...page, route: 'pages/index/index',
    setData(data, done) { this.data = { ...this.data, ...data }; done?.() },
    selectComponent: () => null, createSelectorQuery: () => ({}),
  }
  page.onLoad?.call(nativePage, {})
  page.onShow?.call(nativePage)
  page.onReady?.call(nativePage)
  setTimeout(() => console.log('WeApp App/page module loading and initial lifecycle: PASS'), 500)
} catch (error) {
  console.error(error.stack)
  process.exitCode = 1
}
