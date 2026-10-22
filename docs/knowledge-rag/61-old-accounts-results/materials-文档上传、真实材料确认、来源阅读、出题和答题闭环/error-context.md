# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: materials.spec.ts >> 文档上传、真实材料确认、来源阅读、出题和答题闭环
- Location: e2e-accounts\materials.spec.ts:23:5

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator: locator('.feedback')
Expected: visible
Timeout: 5000ms
Error: element(s) not found

Call log:
  - Expect "toBeVisible" locator('.feedback') with timeout 5000ms
  - waiting for locator('.feedback')

```

```yaml
- text: 9:41
- img
- img
- img
- text: 本轮闯关 ••• 1 / 5
- navigation "切换题目":
  - button "第 1 题": "1"
  - button "第 2 题": "2"
  - button "第 3 题": "3"
  - button "第 4 题": "4"
  - button "第 5 题": "5"
- img
- text: 0 XP 单选题 HTTP 基础 第 1 个问题？
- button "A 选项 A"
- button "B 选项 B"
- button "C 选项 C"
- button "D 选项 D"
- img
- text: 选好后点击“确认本题”，确认前可以修改
- button "上一题" [disabled]
- button "确认本题"
- text: 已答 0 / 5 题，答完自动查看报告
```

# Test source

```ts
  1   | import { apiOrigin, confirmedSession } from './runtime'
  2   | import { test, expect, Page, APIRequestContext } from '@playwright/test'
  3   | import fs from 'node:fs'
  4   | const screenshots = '../docs/quiz-grounding/account-screenshots'
  5   | fs.mkdirSync(screenshots, { recursive: true })
  6   | test.afterEach(async ({ page }) => { await page.unrouteAll({ behavior: 'wait' }) })
  7   | test.beforeEach(async ({ page }) => {
  8   |   await page.route('**/api/v1/**', async route => {
  9   |     const url = new URL(route.request().url()); url.port = new URL(apiOrigin).port
  10  |     await route.fulfill({ response: await route.fetch({ url: url.toString() }) })
  11  |   })
  12  | })
  13  | async function login(page: Page, request: APIRequestContext) {
  14  |   const response = await request.post(apiOrigin + '/api/v1/auth/wechat', { data: { code: `materials-${Date.now()}-${Math.random()}`, agreement_version: '2026-10-12' } })
  15  |   expect(response.status()).toBe(200)
  16  |   const session = (await response.json()).data
  17  |   await page.goto('/')
  18  |   await page.evaluate(token => localStorage.setItem('levelup.auth.v1', JSON.stringify({ data: { token }, expire: null })), session.token)
  19  |   await page.reload(); await expect(page.locator('textarea')).toBeVisible()
  20  |   await expect(page.getByText('正在同步云端学习记录…')).toHaveCount(0)
  21  |   return session
  22  | }
  23  | test('文档上传、真实材料确认、来源阅读、出题和答题闭环', async ({ page, request }) => {
  24  |   await login(page, request)
  25  |   await page.getByText('文档', { exact: true }).click()
  26  |   await page.screenshot({ path: screenshots+'/L02-390.png' })
  27  |   const chooser = page.waitForEvent('filechooser')
  28  |   await page.getByText('点击选择一份文档', { exact: true }).click()
  29  |   await (await chooser).setFiles({ name: 'notes.txt', mimeType: 'text/plain', buffer: Buffer.from('HTTP 每次请求独立。Cookie 用来保存状态。Session 保存会话信息。') })
  30  |   await page.getByText('解析这份文档', { exact: true }).click()
  31  |   await expect(page.getByText('这一关，学这些', { exact: true })).toBeVisible()
  32  |   await page.mouse.move(0,0)
  33  |   await expect(page.locator('.phone-bottom .btn.primary')).toHaveCSS('background-color', 'rgb(51, 106, 232)')
  34  |   await page.screenshot({ path: screenshots+'/L06-390.png' })
  35  |   await page.getByText('查看原文与引用', { exact: true }).click()
  36  |   await expect(page.getByText('HTTP 每次请求独立。Cookie 用来保存状态。Session 保存会话信息。', { exact: true })).toBeVisible()
  37  |   await page.screenshot({ path: screenshots+'/K05-390.png' })
  38  |   await page.locator('.mini-back').click()
  39  |   await page.getByText('确认范围，生成关卡', { exact: true }).click()
  40  |   await page.getByText('开始这一关', { exact: true }).click()
  41  |   for (let i = 0; i < 5; i++) {
  42  |     await expect(page.locator('.question')).toHaveText(`第 ${i + 1} 个问题？`)
  43  |     await page.locator('.option').first().click()
  44  |     if (i === 3) { await page.locator('.option').nth(1).click(); await page.getByText('确认本题', { exact: true }).click() }
> 45  |     if (i < 4) { await expect(page.locator('.feedback')).toBeVisible(); await page.getByText('下一题', { exact: true }).click() }
      |                                                          ^ Error: expect(locator).toBeVisible() failed
  46  |   }
  47  |   await expect(page.getByText('本轮学习报告', { exact: true })).toBeVisible()
  48  |   await page.getByText('逐题回看', { exact: true }).click()
  49  |   await page.locator('.question-records .list-row').first().click()
  50  |   await expect(page.locator('.feedback')).toContainText('notes.txt')
  51  |   await page.screenshot({ path: screenshots+'/L12-source-390.png' })
  52  | })
  53  | test('知识地图与周期报告空态、网页错误和 320px 布局', async ({ page, request }) => {
  54  |   await page.setViewportSize({ width: 320, height: 700 }); await login(page, request)
  55  |   await page.getByText('网页', { exact: true }).click()
  56  |   await page.getByLabel('网页地址').locator('input').fill('http://127.0.0.1/private')
  57  |   await page.getByText('读取网页内容', { exact: true }).click()
  58  |   await expect(page.getByText('请使用可公开访问的 HTTP/HTTPS 链接', { exact: true })).toBeVisible()
  59  |   await page.locator('.mini-back').click(); await page.locator('.mini-back').click()
  60  |   await page.getByText('复盘', { exact: true }).click(); await page.getByText('知识地图', { exact: true }).click()
  61  |   await expect(page.getByText('知识地图，等你点亮', { exact: true })).toBeVisible()
  62  |   await page.screenshot({ path: screenshots+'/R04-empty-320.png' })
  63  |   expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
  64  | })
  65  | test('历史作答聚合、知识节点和周期报告生成导出', async ({ page, request }) => {
  66  |   const account = await login(page, request)
  67  |   const headers = { Authorization: 'Bearer '+account.token }
  68  |   const session = await confirmedSession(request, headers)
  69  |   for (const [i, selected] of [['A'], ['A','B'], ['B']].entries()) await request.post(`${apiOrigin}/api/v1/attempts/${session.id}/answers`, { headers, data: { question_id: 'q'+i, selected, elapsed_ms: 1000 } })
  70  |   await page.reload(); await page.getByText('复盘', { exact: true }).click()
  71  |   await page.getByText('知识地图', { exact: true }).click(); await expect(page.locator('.knowledge-map')).toBeVisible()
  72  |   await expect(page.locator('.atlas-edge').first()).toBeAttached()
  73  |   await page.screenshot({ path: screenshots+'/R04-390.png' })
  74  |   await page.setViewportSize({ width: 320, height: 700 })
  75  |   expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
  76  |   await page.screenshot({ path: screenshots+'/R04-320.png' })
  77  |   await page.setViewportSize({ width: 390, height: 812 })
  78  |   await page.locator('.mini-back').click(); await page.getByText('数据分析', { exact: true }).click()
  79  |   await expect(page.locator('.stat-grid')).toContainText('67%')
  80  |   await expect(page.locator('.chart-image')).toBeVisible()
  81  |   await page.screenshot({ path: screenshots+'/R05-390.png' })
  82  |   await page.getByText('生成报告', { exact: false }).click()
  83  |   await expect(page.locator('.phone-bottom .btn')).not.toHaveAttribute('disabled', '')
  84  |   await page.mouse.move(0,0)
  85  |   await expect(page.locator('.phone-bottom .btn.primary')).toHaveCSS('background-color', 'rgb(51, 106, 232)')
  86  |   await page.screenshot({ path: screenshots+'/R06-390.png' })
  87  |   await page.setViewportSize({ width: 320, height: 700 })
  88  |   expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
  89  |   await page.screenshot({ path: screenshots+'/R06-320.png' })
  90  |   await page.setViewportSize({ width: 390, height: 812 })
  91  |   await page.getByText('生成这段时间的报告', { exact: true }).click()
  92  |   await expect(page.locator('.app-shell')).toHaveAttribute('data-id', 'R07')
  93  |   await expect(page.locator('.chart-image')).toBeVisible()
  94  |   await page.screenshot({ path: screenshots+'/R07-390.png' })
  95  |   await page.setViewportSize({ width: 320, height: 700 })
  96  |   expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
  97  |   await page.screenshot({ path: screenshots+'/R07-320.png' })
  98  |   const download = page.waitForEvent('download'); await page.getByText('保存文字报告', { exact: true }).click()
  99  |   expect((await download).suggestedFilename()).toContain('.txt')
  100 | })
  101 | 
  102 | test('已清理的缓存解析任务能退出轮询并重新选择材料', async ({ page, request }) => {
  103 |   const account = await login(page, request)
  104 |   await page.evaluate(uid => localStorage.setItem('levelup.material-job.'+uid, JSON.stringify({ data: { id: 'expired-job', kind: 'document' }, expire: null })), account.user.id)
  105 |   await page.route('**/api/v1/material-jobs/expired-job', route => route.fulfill({ status: 404, json: { code: 'NOT_FOUND', message: '材料或报告不存在' } }))
  106 |   await page.getByText('文档', { exact: true }).click()
  107 |   await expect(page.locator('.app-shell')).toHaveAttribute('data-id', 'E05')
  108 |   await page.getByText('返回修改材料', { exact: true }).click()
  109 |   await expect(page.getByText('点击选择一份文档', { exact: true })).toBeVisible()
  110 |   expect(await page.evaluate(uid => localStorage.getItem('levelup.material-job.'+uid), account.user.id)).toBeNull()
  111 | })
  112 | 
  113 | test('取消解析后迟到的材料响应不能跳回学习范围', async ({ page, request }) => {
  114 |   const account = await login(page, request)
  115 |   await page.evaluate(uid => localStorage.setItem('levelup.material-job.'+uid, JSON.stringify({ data: { id: 'late-job', kind: 'document' }, expire: null })), account.user.id)
  116 |   await page.route('**/api/v1/material-jobs/late-job', route => route.fulfill({ json: { code: 0, data: { id: 'late-job', status: 'succeeded', material_id: 'late-material' } } }))
  117 |   await page.route('**/api/v1/material-jobs/late-job/cancel', route => route.fulfill({ json: { code: 0, data: { status: 'cancelled' } } }))
  118 |   let release!: () => void, arrived!: () => void, finished!: () => void
  119 |   const gate = new Promise<void>(resolve => { release = resolve })
  120 |   const requested = new Promise<void>(resolve => { arrived = resolve })
  121 |   const returned = new Promise<void>(resolve => { finished = resolve })
  122 |   await page.route('**/api/v1/materials/late-material', async route => {
  123 |     arrived(); await gate
  124 |     try { await route.fulfill({ json: { code: 0, data: { id: 'late-material', title: '迟到的材料', learning_title: '迟到的知识', summary: '摘要', source_type: 'document', segments: [{ id: 's1', text: '正文' }], points: [{ name: '知识', segment_ids: ['s1'] }] } } }) } finally { finished() }
  125 |   })
  126 |   try {
  127 |     await page.getByText('文档', { exact: true }).click(); await requested
  128 |     await page.getByText('取消解析，返回输入', { exact: true }).click()
  129 |     release(); await returned
  130 |     await expect(page.locator('.app-shell')).toHaveAttribute('data-id', 'L02')
  131 |     await expect(page.getByText('这一关，学这些', { exact: true })).toHaveCount(0)
  132 |   } finally { release() }
  133 | })
  134 | 
```