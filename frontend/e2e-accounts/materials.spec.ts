import { apiOrigin, confirmedSession } from './runtime'
import { test, expect, Page, APIRequestContext } from '@playwright/test'
import fs from 'node:fs'
const screenshots = '../docs/quiz-grounding/account-screenshots'
fs.mkdirSync(screenshots, { recursive: true })
test.afterEach(async ({ page }) => { await page.unrouteAll({ behavior: 'wait' }) })
test.beforeEach(async ({ page }) => {
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url()); url.port = new URL(apiOrigin).port
    await route.fulfill({ response: await route.fetch({ url: url.toString() }) })
  })
})
async function login(page: Page, request: APIRequestContext) {
  const response = await request.post(apiOrigin + '/api/v1/auth/wechat', { data: { code: `materials-${Date.now()}-${Math.random()}`, agreement_version: '2026-10-12' } })
  expect(response.status()).toBe(200)
  const session = (await response.json()).data
  await page.goto('/')
  await page.evaluate(token => localStorage.setItem('levelup.auth.v1', JSON.stringify({ data: { token }, expire: null })), session.token)
  await page.reload(); await expect(page.locator('textarea')).toBeVisible()
  await expect(page.getByText('正在同步云端学习记录…')).toHaveCount(0)
  return session
}
test('文档上传、真实材料确认、来源阅读、出题和答题闭环', async ({ page, request }) => {
  await login(page, request)
  await page.getByText('文档', { exact: true }).click()
  await page.screenshot({ path: screenshots+'/L02-390.png' })
  const chooser = page.waitForEvent('filechooser')
  await page.getByText('点击选择一份文档', { exact: true }).click()
  await (await chooser).setFiles({ name: 'notes.txt', mimeType: 'text/plain', buffer: Buffer.from('HTTP 每次请求独立。Cookie 用来保存状态。Session 保存会话信息。') })
  await page.getByText('解析这份文档', { exact: true }).click()
  await expect(page.getByText('这一关，学这些', { exact: true })).toBeVisible()
  await page.mouse.move(0,0)
  await expect(page.locator('.phone-bottom .btn.primary')).toHaveCSS('background-color', 'rgb(51, 106, 232)')
  await page.screenshot({ path: screenshots+'/L06-390.png' })
  await page.getByText('查看原文与引用', { exact: true }).click()
  await expect(page.getByText('HTTP 每次请求独立。Cookie 用来保存状态。Session 保存会话信息。', { exact: true })).toBeVisible()
  await page.screenshot({ path: screenshots+'/K05-390.png' })
  await page.locator('.mini-back').click()
  await page.getByText('确认范围，生成关卡', { exact: true }).click()
  await page.getByText('开始这一关', { exact: true }).click()
  for (let i = 0; i < 5; i++) {
    await expect(page.locator('.question')).toHaveText(`第 ${i + 1} 个问题？`)
    await page.locator('.option').first().click()
    if (i === 3) await page.locator('.option').nth(1).click()
    await page.getByText('确认本题', { exact: true }).click()
    if (i < 4) { await expect(page.locator('.feedback')).toBeVisible(); await page.getByText('下一题', { exact: true }).click() }
  }
  await expect(page.getByText('本轮学习报告', { exact: true })).toBeVisible()
  await page.getByText('逐题回看', { exact: true }).click()
  await page.locator('.question-records .list-row').first().click()
  await expect(page.locator('.feedback')).toContainText('notes.txt')
  await page.screenshot({ path: screenshots+'/L12-source-390.png' })
})
test('知识地图与周期报告空态、网页错误和 320px 布局', async ({ page, request }) => {
  await page.setViewportSize({ width: 320, height: 700 }); await login(page, request)
  await page.getByText('网页', { exact: true }).click()
  await page.getByLabel('网页地址').locator('input').fill('http://127.0.0.1/private')
  await page.getByText('读取网页内容', { exact: true }).click()
  await expect(page.getByText('请使用可公开访问的 HTTP/HTTPS 链接', { exact: true })).toBeVisible()
  await page.locator('.mini-back').click(); await page.locator('.mini-back').click()
  await page.getByText('复盘', { exact: true }).click(); await page.getByText('知识地图', { exact: true }).click()
  await expect(page.getByText('知识地图，等你点亮', { exact: true })).toBeVisible()
  await page.screenshot({ path: screenshots+'/R04-empty-320.png' })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
})
test('历史作答聚合、知识节点和周期报告生成导出', async ({ page, request }) => {
  const account = await login(page, request)
  const headers = { Authorization: 'Bearer '+account.token }
  const session = await confirmedSession(request, headers)
  for (const [i, selected] of [['A'], ['A','B'], ['B']].entries()) await request.post(`${apiOrigin}/api/v1/attempts/${session.id}/answers`, { headers, data: { question_id: 'q'+i, selected, elapsed_ms: 1000 } })
  await page.reload(); await page.getByText('复盘', { exact: true }).click()
  await page.getByText('知识地图', { exact: true }).click(); await expect(page.locator('.knowledge-map')).toBeVisible()
  await expect(page.locator('.atlas-edge').first()).toBeAttached()
  await page.screenshot({ path: screenshots+'/R04-390.png' })
  await page.setViewportSize({ width: 320, height: 700 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
  await page.screenshot({ path: screenshots+'/R04-320.png' })
  await page.setViewportSize({ width: 390, height: 812 })
  await page.locator('.mini-back').click(); await page.getByText('数据分析', { exact: true }).click()
  await expect(page.locator('.stat-grid')).toContainText('67%')
  await expect(page.locator('.chart-image')).toBeVisible()
  await page.screenshot({ path: screenshots+'/R05-390.png' })
  await page.getByText('生成报告', { exact: false }).click()
  await expect(page.locator('.phone-bottom .btn')).not.toHaveAttribute('disabled', '')
  await page.mouse.move(0,0)
  await expect(page.locator('.phone-bottom .btn.primary')).toHaveCSS('background-color', 'rgb(51, 106, 232)')
  await page.screenshot({ path: screenshots+'/R06-390.png' })
  await page.setViewportSize({ width: 320, height: 700 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
  await page.screenshot({ path: screenshots+'/R06-320.png' })
  await page.setViewportSize({ width: 390, height: 812 })
  await page.getByText('生成这段时间的报告', { exact: true }).click()
  await expect(page.locator('.app-shell')).toHaveAttribute('data-id', 'R07')
  await expect(page.locator('.chart-image')).toBeVisible()
  await page.screenshot({ path: screenshots+'/R07-390.png' })
  await page.setViewportSize({ width: 320, height: 700 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
  await page.screenshot({ path: screenshots+'/R07-320.png' })
  const download = page.waitForEvent('download'); await page.getByText('保存文字报告', { exact: true }).click()
  expect((await download).suggestedFilename()).toContain('.txt')
})

test('已清理的缓存解析任务能退出轮询并重新选择材料', async ({ page, request }) => {
  const account = await login(page, request)
  await page.evaluate(uid => localStorage.setItem('levelup.material-job.'+uid, JSON.stringify({ data: { id: 'expired-job', kind: 'document' }, expire: null })), account.user.id)
  await page.route('**/api/v1/material-jobs/expired-job', route => route.fulfill({ status: 404, json: { code: 'NOT_FOUND', message: '材料或报告不存在' } }))
  await page.getByText('文档', { exact: true }).click()
  await expect(page.locator('.app-shell')).toHaveAttribute('data-id', 'E05')
  await page.getByText('返回修改材料', { exact: true }).click()
  await expect(page.getByText('点击选择一份文档', { exact: true })).toBeVisible()
  expect(await page.evaluate(uid => localStorage.getItem('levelup.material-job.'+uid), account.user.id)).toBeNull()
})

test('取消解析后迟到的材料响应不能跳回学习范围', async ({ page, request }) => {
  const account = await login(page, request)
  await page.evaluate(uid => localStorage.setItem('levelup.material-job.'+uid, JSON.stringify({ data: { id: 'late-job', kind: 'document' }, expire: null })), account.user.id)
  await page.route('**/api/v1/material-jobs/late-job', route => route.fulfill({ json: { code: 0, data: { id: 'late-job', status: 'succeeded', material_id: 'late-material' } } }))
  await page.route('**/api/v1/material-jobs/late-job/cancel', route => route.fulfill({ json: { code: 0, data: { status: 'cancelled' } } }))
  let release!: () => void, arrived!: () => void, finished!: () => void
  const gate = new Promise<void>(resolve => { release = resolve })
  const requested = new Promise<void>(resolve => { arrived = resolve })
  const returned = new Promise<void>(resolve => { finished = resolve })
  await page.route('**/api/v1/materials/late-material', async route => {
    arrived(); await gate
    try { await route.fulfill({ json: { code: 0, data: { id: 'late-material', title: '迟到的材料', learning_title: '迟到的知识', summary: '摘要', source_type: 'document', segments: [{ id: 's1', text: '正文' }], points: [{ name: '知识', segment_ids: ['s1'] }] } } }) } finally { finished() }
  })
  try {
    await page.getByText('文档', { exact: true }).click(); await requested
    await page.getByText('取消解析，返回输入', { exact: true }).click()
    release(); await returned
    await expect(page.locator('.app-shell')).toHaveAttribute('data-id', 'L02')
    await expect(page.getByText('这一关，学这些', { exact: true })).toHaveCount(0)
  } finally { release() }
})
