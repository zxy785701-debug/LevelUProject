import { test, expect, Page, APIRequestContext } from '@playwright/test'
import fs from 'node:fs'
const origin = 'http://127.0.0.1:8002'
const screenshots = process.env.KNOWLEDGE_SCREENSHOTS || '../docs/knowledge-rag/page-screenshots'
fs.mkdirSync(screenshots, { recursive: true })
test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    const removePreviewOverlay = () => document.getElementById('webpack-dev-server-client-overlay')?.remove()
    document.addEventListener('DOMContentLoaded', () => {
      new MutationObserver(removePreviewOverlay).observe(document.documentElement, { childList: true, subtree: true })
      removePreviewOverlay()
    })
  })
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url()); url.port = '8002'
    await route.fulfill({ response: await route.fetch({ url: url.toString() }) })
  })
})
test.afterEach(async ({ page }) => { await page.unrouteAll({ behavior: 'wait' }) })
async function login(page: Page, request: APIRequestContext) {
  const response = await request.post(origin + '/api/v1/auth/wechat', { data: { code: 'kb-e2e-' + Date.now() + Math.random(), agreement_version: '2026-10-12' } })
  expect(response.status()).toBe(200)
  const account = (await response.json()).data
  await page.goto('/')
  await page.evaluate(token => localStorage.setItem('levelup.auth.v1', JSON.stringify({ data: { token }, expire: null })), account.token)
  await page.reload(); await expect(page.locator('textarea')).toBeVisible()
  // Existing Sass deprecation warnings open the development-server overlay.
  // They remain in the build log; close the overlay to exercise the app itself.
  await page.locator('#webpack-dev-server-client-overlay').evaluateAll(nodes => nodes.forEach(n => n.remove()))
  await expect(page.getByText('正在同步云端学习记录…')).toHaveCount(0)
  return { ...account, headers: { Authorization: 'Bearer ' + account.token } }
}
async function enter(page: Page) {
  await page.getByText('我的', { exact: true }).click()
  await page.getByText('私有知识库', { exact: true }).click()
  await expect(page.getByTestId('knowledge-library')).toBeVisible()
  await expect(page.getByText('添加资料', { exact: true })).toBeVisible()
}
async function upload(page: Page, name = '协议学习笔记.md') {
  await page.getByText('添加资料', { exact: true }).click()
  await expect(page.getByText('检索片段发送 DeepSeek', { exact: false })).toBeVisible()
  const chooser = page.waitForEvent('filechooser')
  await page.getByRole('button', { name: /^选择文档/ }).click()
  await (await chooser).setFiles({ name, mimeType: 'text/markdown', buffer: Buffer.from('# 请求与会话\nHTTP 每次请求独立。Cookie 用来保存状态。Session 保存会话信息。\n\n## 错误处理\nHTTP 404 表示未找到请求资源。') })
  await page.getByRole('button', { name: '添加并处理材料', exact: true }).click()
  await expect(page.getByText('资料已就绪，可以提问或准备关卡。', { exact: true })).toBeVisible()
}
async function ask(page: Page, question = '根据资料解释 HTTP 与会话') {
  await page.getByRole('button', { name: '向资料提问', exact: true }).click()
  await page.locator('textarea').fill(question)
  if (await page.locator('.knowledge-check taro-checkbox-core').first().getAttribute('checked') !== 'true') await page.getByText('全部已就绪资料（提交时固定版本）', { exact: true }).click()
  await page.getByRole('button', { name: '提交问题', exact: true }).click()
  await expect(page.getByTestId('knowledge-answer')).toBeVisible()
}
async function snapshot(page: Page, name: string) {
  for (const width of [390, 320]) {
    await page.setViewportSize({ width, height: 812 })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
    await page.screenshot({ path: screenshots + '/' + name + '-' + width + '.png' })
  }
  await page.setViewportSize({ width: 390, height: 812 })
}
test('真实存储闭环：Markdown→问答来源→原问题出题→多选主题→确认答题→报告', async ({ page, request }) => {
  const account = await login(page, request); await enter(page)
  await upload(page, '中文长文件名_请求会话与HTTP错误处理机制_用于验证小屏自动换行不横向溢出.md')
  await snapshot(page, 'library')
  const docs = (await (await request.get(origin + '/api/v1/knowledge/documents', { headers: account.headers })).json()).data
  expect(docs.total).toBe(1)
  await page.getByRole('button', { name: /^查看资料：/ }).first().click()
  await expect(page.getByText('原文引用', { exact: true })).toBeVisible()
  await snapshot(page, 'document')
  await page.locator('.mini-back').click()
  await page.getByRole('button', { name: '向资料提问', exact: true }).click()
  await expect(page.locator('taro-switch-core')).toHaveAttribute('checked', 'true')
  await page.locator('textarea').fill('根据资料解释 HTTP 与会话')
  await page.getByText('全部已就绪资料（提交时固定版本）', { exact: true }).click()
  await snapshot(page, 'question')
  await page.getByRole('button', { name: '提交问题', exact: true }).click()
  await expect(page.getByTestId('knowledge-answer')).toBeVisible()
  const me = (await (await request.get(origin + '/api/v1/me', { headers: account.headers })).json()).data
  expect(me.stats.xp).toBe(0); expect(me.stats.coins).toBe(0)
  await snapshot(page, 'answer')
  await page.getByRole('button', { name: '查看本段引用（1）', exact: true }).click()
  await expect(page.locator('.knowledge-citation')).toContainText('v1')
  await expect(page.locator('.source-excerpt')).toContainText('HTTP 每次请求独立')
  await snapshot(page, 'source')
  await page.locator('.mini-back').click()
  await page.getByRole('button', { name: '按这个问题出题', exact: true }).click()
  await page.getByRole('button', { name: /出题设置/ }).click()
  await expect(page.locator('textarea')).toHaveValue('根据资料解释 HTTP 与会话')
  await page.getByRole('button', { name: '生成知识库关卡', exact: true }).click()
  await expect(page.getByTestId('knowledge-confirm')).toBeVisible()
  await expect(page.locator('.knowledge-prototype-topic.selected')).toHaveCount(1)
  await page.locator('.knowledge-prototype-topic').nth(1).click()
  await expect(page.locator('.knowledge-prototype-topic.selected')).toHaveCount(2)
  await snapshot(page, 'scope')
  await page.getByRole('button', { name: '确认范围，生成关卡', exact: true }).click()
  await page.getByRole('button', { name: '取消后台处理', exact: true }).click()
  await page.getByRole('button', { name: '重试原任务', exact: true }).click()
  await page.locator('.mini-back').click()
  await page.locator('.knowledge-card').filter({ hasText: '生成学习关卡' }).first().getByRole('button', { name: '恢复原提交', exact: true }).click()
  await page.getByText('开始这一关', { exact: true }).click()
  for (let i = 0; i < 3; i++) {
    await expect(page.locator('.question')).toHaveText(`第 ${i + 1} 个问题？`)
    await page.locator('.option').first().click()
    if (i === 1) await page.locator('.option').nth(1).click()
    await page.getByText('确认本题', { exact: true }).click()
    if (i < 2) { await expect(page.locator('.feedback')).toBeVisible(); await page.getByText('下一题', { exact: true }).click() }
  }
  await expect(page.getByText('本轮学习报告', { exact: true })).toBeVisible()
  await snapshot(page, 'report')
  await page.locator('.mini-back').click()
  await expect(page.locator('textarea')).toBeVisible()
})
test('断开响应与重新打开：恢复同一上传任务，不重复创建文档', async ({ page, request }) => {
  const account = await login(page, request); await enter(page)
  await page.getByText('添加资料', { exact: true }).click()
  const chooser = page.waitForEvent('filechooser'); await page.getByRole('button', { name: /^选择文档/ }).click()
  await (await chooser).setFiles({ name: '恢复原提交.txt', mimeType: 'text/plain', buffer: Buffer.from('HTTP 404 表示资源未找到。') })
  await page.route('**/api/v1/knowledge/documents/upload', async route => {
    const url = new URL(route.request().url()); url.port = '8002'
    await route.fetch({ url: url.toString() }); await route.abort('failed')
  })
  await page.getByRole('button', { name: '添加并处理材料', exact: true }).click()
  await expect(page.locator('.knowledge-error')).toBeVisible()
  await page.reload(); await expect(page.locator('textarea')).toBeVisible(); await enter(page)
  await page.getByRole('button', { name: '恢复原提交', exact: true }).click()
  await expect(page.getByText('资料已就绪，可以提问或准备关卡。', { exact: true })).toBeVisible()
  const result = (await (await request.get(origin + '/api/v1/knowledge/documents', { headers: account.headers })).json()).data
  expect(result.total).toBe(1)
})
test('资料不足、问答删除和资料删除后的来源快照', async ({ page, request }) => {
  const account = await login(page, request); await enter(page); await upload(page)
  await ask(page, '资料没有记载的遥远星球数值')
  await expect(page.getByText('现有资料不足以支持可靠回答，请补充资料或缩小问题。', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '删除这条问答', exact: true }).click()
  await page.locator('.taro-model__confirm').click()
  await expect(page.getByTestId('knowledge-history')).toBeVisible()
  await page.locator('.mini-back').click(); await ask(page)
  const docs = (await (await request.get(origin + '/api/v1/knowledge/documents', { headers: account.headers })).json()).data
  expect((await request.delete(origin + '/api/v1/knowledge/documents/' + docs.items[0].id, { headers: account.headers })).status()).toBe(200)
  await page.locator('.mini-back').click(); await page.getByText('查看问答', { exact: true }).click()
  await page.getByRole('button', { name: '查看问答', exact: true }).click()
  await page.getByRole('button', { name: '查看全部引用', exact: true }).click()
  await expect(page.locator('.knowledge-citation')).toContainText('原资料已删除')
  await snapshot(page, 'deleted-source')
  await page.locator('.mini-back').click(); await page.getByRole('button', { name: '按这个问题出题', exact: true }).click()
  await expect(page.locator('.knowledge-error')).toContainText('重新选择资料')
})
test('公开网页、已有材料复制、取消重建后重试及资料删除', async ({ page, request }) => {
  const account = await login(page, request); await enter(page)
  await page.getByText('添加资料', { exact: true }).click()
  await page.getByText('添加链接', { exact: true }).click()
  await page.locator('input[placeholder="粘贴公开网页链接"]').fill('https://example.com/learn')
  await page.getByRole('button', { name: '添加并处理材料', exact: true }).click()
  await expect(page.getByText('资料已就绪，可以提问或准备关卡。', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: /^查看资料：/ }).click()
  await page.getByRole('button', { name: '重建索引', exact: true }).click()
  await page.getByRole('button', { name: '取消后台处理', exact: true }).click()
  await expect(page.getByRole('button', { name: '重试原任务', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '重试原任务', exact: true }).click()
  await expect(page.getByText('资料已就绪，可以提问或准备关卡。', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: /^查看资料：/ }).click()
  await page.getByRole('button', { name: '移除此材料', exact: true }).click()
  await page.locator('.taro-model__confirm').click()
  await expect(page.getByText('资料已删除，原文与索引正在后台清理。', { exact: true })).toBeVisible()
  const old = await request.post(origin + '/api/v1/materials/document', { headers: { ...account.headers, 'Idempotency-Key': 'existing-' + Date.now() }, multipart: { file: { name: '已有材料.txt', mimeType: 'text/plain', buffer: Buffer.from('HTTP 每次请求独立。Cookie 用来保存状态。Session 保存会话信息。') } } })
  expect(old.status()).toBe(200)
  const materialJob = (await old.json()).data
  await expect.poll(async () => (await (await request.get(origin + '/api/v1/material-jobs/' + materialJob.id, { headers: account.headers })).json()).data.status).toBe('succeeded')
  await page.getByText('添加资料', { exact: true }).click()
  await page.getByRole('button', { name: '从已有材料添加', exact: true }).click()
  await page.getByRole('button', { name: '复制到知识库', exact: true }).click()
  await expect(page.getByText('资料已就绪，可以提问或准备关卡。', { exact: true })).toBeVisible()
  const docs = (await (await request.get(origin + '/api/v1/knowledge/documents', { headers: account.headers })).json()).data
  expect(docs.total).toBe(1)
  await snapshot(page, 'copied-material')
})
test('文件选择期间切后台可返回；切换账号不显示前一账号资料或草稿', async ({ page, request }) => {
  const account = await login(page, request); await enter(page)
  await page.getByText('添加资料', { exact: true }).click()
  const chooser = page.waitForEvent('filechooser'); await page.getByRole('button', { name: /^选择文档/ }).click()
  await page.evaluate(() => { Object.defineProperty(document, 'hidden', { configurable: true, get: () => true }); document.dispatchEvent(new Event('visibilitychange')) })
  await (await chooser).setFiles({ name: '切后台选择.md', mimeType: 'text/markdown', buffer: Buffer.from('# 笔记\nHTTP 每次请求独立。') })
  await page.evaluate(() => { Object.defineProperty(document, 'hidden', { configurable: true, get: () => false }); document.dispatchEvent(new Event('visibilitychange')) })
  await expect(page.getByRole('button', { name: '添加并处理材料', exact: true })).toBeEnabled()
  await page.getByRole('button', { name: '添加并处理材料', exact: true }).click()
  await expect(page.getByText('资料已就绪，可以提问或准备关卡。', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '向资料提问', exact: true }).click()
  await page.locator('textarea').fill('仅前一账号的草稿')
  const second = await login(page, request)
  expect(second.user.id).not.toBe(account.user.id)
  await enter(page)
  await expect(page.getByText('切后台选择.md', { exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: '向资料提问', exact: true }).click()
  await expect(page.locator('textarea')).toHaveValue('')
})
