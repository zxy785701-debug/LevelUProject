// Validate Taro's output with WeChat's compiler; a successful Taro build alone
// does not guarantee that the resulting styles use valid WXSS selectors.
const fs = require('node:fs')
const path = require('node:path')
const { spawnSync } = require('node:child_process')

const compiler = process.argv[2] || process.env.WECHAT_WXSS_COMPILER
if (!compiler || !fs.existsSync(compiler)) {
  console.error('Pass the installed WeChat wcsc.exe path, or set WECHAT_WXSS_COMPILER.')
  process.exit(1)
}
const output = path.resolve(__dirname, '../dist')
function findStyles(directory) {
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const file = path.join(directory, entry.name)
    return entry.isDirectory() ? findStyles(file) : file.endsWith('.wxss') ? [file] : []
  })
}
const files = findStyles(output).map((file) => path.relative(output, file).replace(/\\/g, '/'))
if (!files.length) throw new Error('No WXSS output found; run build:weapp first.')
const result = spawnSync(compiler, ['-o', process.platform === 'win32' ? 'nul' : '/dev/null', ...files], {
  cwd: output,
  encoding: 'utf8',
  timeout: 30000,
  windowsHide: true,
})
const report = {
  passed: result.status === 0 && !result.error && !/ERR:/.test(result.stderr || ''),
  files,
  exit_code: result.status,
  diagnostics: result.error?.message || result.stderr?.trim() || '',
}
console.log(JSON.stringify(report, null, 2))
process.exitCode = report.passed ? 0 : 1
