import { test, expect, Page } from '@playwright/test'

const now = new Date().toISOString()
const evidence = [{ id: 'e1', text: 'Harness engineering builds environments, tools and feedback loops for coding agents.', title: 'Harness engineering reference', url: 'https://example.org/harness', content_kind: 'full_extract', retrieved_at: now, published_at: null, truncated: false, context_truncated: false }]
const candidate = (id: string, domain: string) => ({ id, topic: 'Harness Engineering', domain, description: '请选择想学的具体领域', focuses: [{ id: 'f1', name: '工具与反馈', description: '环境、工具和反馈循环', points: [{ id: 'p1', name: '工具契约', evidence_ids: ['e1'], evidence_status: 'available' }, { id: 'p2', name: '反馈循环', evidence_ids: ['e1'], evidence_status: 'available' }] }] })
const preparation = (extra = {}) => ({ id: 'prep-1', version: 1, input_text: 'Harness Engineering', status: 'ready', stage: 'ready', content: { candidates: [candidate('ai', 'AI 工程'), candidate('hardware', '线束工程')] }, grounding: { status: 'source_backed' }, evidence, retry_after_seconds: 0, created_at: now, expires_at: new Date(Date.now() + 86400000).toISOString(), ...extra })
const session = { id: 's1', mode: 'new', answers: [], cursor: 0, pending_ms: 0, started_at: now, quiz: { id: 'q1', created_at: now, source_text: 'Harness Engineering', title: '工具与反馈关卡', summary: '围绕确认范围学习', difficulty: 'easy', questions: [{ id: 'q01', type: 'single', stem: '工具契约的作用是什么？', options: [{ id: 'A', text: '明确输入输出' }, { id: 'B', text: '忽略反馈' }], answers: [], explanation: '', knowledge_point: '工具契约' }] } }
async function setup(page: Page, handler?: (path: string, method: string, body: any) => any) {
  await page.addInitScript(() => localStorage.setItem('levelup.auth.v1', JSON.stringify({ data: { token: 'grounding-ui-test' }, expire: null })))
  await page.route('**/api/v1/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname
    let body: any; try { body = request.postDataJSON() } catch {}
    let result = handler?.(path, request.method(), body)
    if (result instanceof Promise) result = await result
    if (result === undefined) {
      if (path === '/api/v1/me') result = { id: 'ui-grounding', nickname: '学习者', avatar_version: 0, stats: { xp: 0, coins: 0, level: 1, topics: 0, streak: 0, accuracy: 0 }, quota: { remaining: 10, daily_limit: 10 } }
      else if (path === '/api/v1/learning') result = { version: 1, sessions: [], wrongs: {}, welcome: true, draft: { text: '', count: 5, difficulty: 'easy' } }
      else if (path.startsWith('/api/v1/quiz/preparations')) result = preparation()
      else if (path === '/api/v1/quiz/generate') result = { kind: 'generation_operation', key: request.headers()['idempotency-key'], status: 'running', stage: 'generating', retry_after_seconds: 0, deadline: new Date(Date.now() + 300000).toISOString() }
      else if (path.startsWith('/api/v1/operations/')) result = { status: 'succeeded', stage: 'succeeded', result: session }
      else throw new Error('Unexpected UI request: ' + path)
    }
    await route.fulfill({ json: { code: 0, data: result } })
  })
  await page.goto('/')
  await expect(page.locator('textarea')).toBeVisible()
}
async function start(page: Page, text: string) { await page.locator('textarea').fill(text); await page.getByText('生成我的关卡', { exact: false }).click() }
async function select(page: Page) {
  await expect(page.locator('.scope-option.active')).toHaveCount(1)
}
test('默认推荐主题，可多选、取消，预览后一起提交且无额外选择步骤', async ({ page }) => {
  const submitted: any[] = []
  await setup(page, (path, method, body) => { if (path === '/api/v1/quiz/generate' && method === 'POST') submitted.push(body) })
  await start(page, 'Harness Engineering')
  await expect(page.locator('.scope-option.active')).toHaveCount(1)
  await page.getByText('Harness Engineering · AI 工程', { exact: true }).click()
  await expect(page.getByText('确认范围，生成关卡', { exact: true })).toHaveAttribute('disabled', '')
  await page.getByText('Harness Engineering · AI 工程', { exact: true }).click()
  expect(submitted).toHaveLength(0)
  await page.getByText('预览学习资料', { exact: true }).click()
  await expect(page.getByText(evidence[0].text, { exact: true })).toBeVisible()
  await expect(page.getByText('获取：' + now.slice(0, 10) + ' · 发布：未知日期', { exact: true })).toBeVisible()
  await page.getByText('返回确认范围', { exact: true }).click()
  await select(page)
  await page.getByText('Harness Engineering · 线束工程', { exact: true }).click()
  await expect(page.locator('.scope-option.active')).toHaveCount(2)
  await expect(page.getByText('选择内容方向', { exact: true })).toHaveCount(0)
  await expect(page.getByText('本轮知识点', { exact: true })).toHaveCount(0)
  await page.screenshot({ path: '../docs/quiz-grounding/screenshots/scope-confirmation.png' })
  await page.getByText('确认范围，生成关卡', { exact: true }).click()
  await expect(page.getByText('开始这一关', { exact: true })).toBeVisible()
  expect(submitted).toHaveLength(1)
  expect(submitted[0]).toMatchObject({ preparation_id: 'prep-1', candidate_ids: ['ai', 'hardware'] })
})
test('网址与附加说明进入材料读取，保持联网补充默认关闭', async ({ page }) => {
  let parsed: any, generated: any, prepares = 0
  await setup(page, (path, method, body) => {
    if (path === '/api/v1/quiz/preparations' && method === 'POST') prepares++
    if (path === '/api/v1/materials/web') { parsed = body; return { id: 'j1', status: 'running', stage: 'extracting' } }
    if (path === '/api/v1/material-jobs/j1') return { id: 'j1', status: 'succeeded', stage: 'succeeded', material_id: 'm1' }
    if (path === '/api/v1/materials/m1') return { id: 'm1', title: '指定页面', learning_title: '网页应用案例', summary: '页面真实摘要', source_type: 'web', segments: evidence, points: [{ name: '应用案例', segment_ids: ['e1'] }], search_available: true }
    if (path === '/api/v1/quiz/generate') generated = body
  })
  await start(page, 'https://example.org/harness 重点学习 AI 工程的应用案例')
  await expect(page.getByLabel('网页地址').locator('input')).toHaveValue('https://example.org/harness')
  await expect(page.getByLabel('网页学习说明').locator('input')).toHaveValue('重点学习 AI 工程的应用案例')
  await page.getByText('读取网页内容', { exact: true }).click()
  await expect(page.getByText('网页应用案例', { exact: true })).toBeVisible()
  expect(parsed).toMatchObject({ url: 'https://example.org/harness', learning_instruction: '重点学习 AI 工程的应用案例' })
  expect(prepares).toBe(0)
  await expect(page.locator('input[type=checkbox]')).not.toBeChecked()
  await page.getByText('确认范围，生成关卡', { exact: true }).click()
  await expect(page.getByText('开始这一关', { exact: true })).toBeVisible()
  expect(generated).toMatchObject({ material_id: 'm1', point_ids: ['e1'], supplement: false, execution: 'background' })
})
test('未核实范围仍需确认，小屏可操作且返回保留输入', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 568 })
  await setup(page, path => path.startsWith('/api/v1/quiz/preparations') ? preparation({ grounding: { status: 'unverified', reason_code: 'SEARCH_UNAVAILABLE' }, evidence: [], content: { candidates: [candidate('ai', 'AI 工程')] } }) : undefined)
  await start(page, 'Harness Engineering')
  await expect(page.getByText('未联网核实', { exact: true })).toBeVisible()
  await expect(page.getByText('确认范围，生成关卡', { exact: true })).toBeEnabled()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.screenshot({ path: '../docs/quiz-grounding/screenshots/scope-unverified-320.png' })
  await page.getByText('返回修改主题', { exact: true }).click()
  await expect(page.locator('textarea')).toHaveValue('Harness Engineering')
})
test('离开后恢复同一后台操作，限流等待不新建学习范围', async ({ page }) => {
  let completed = false, submitted = 0, preparations = 0
  const keys: string[] = []
  await setup(page, (path, method) => {
    if (path === '/api/v1/quiz/preparations' && method === 'POST') preparations++
    if (path === '/api/v1/quiz/generate' && method === 'POST') submitted++
    if (path.startsWith('/api/v1/operations/')) { keys.push(path); return completed ? { status: 'succeeded', result: session } : { status: 'running', stage: 'waiting_rate_limit', retry_after_seconds: 2 } }
  })
  await start(page, 'Harness Engineering'); await select(page)
  await page.getByText('确认范围，生成关卡', { exact: true }).click()
  await expect(page.getByText('正在等待模型额度', { exact: true })).toBeVisible()
  await expect(page.locator('.generation-progress')).toBeVisible()
  await expect(page.locator('.generation-progress .weui-progress__inner-bar')).toHaveCSS('background-color', 'rgb(51, 106, 232)')
  await page.getByText('返回首页，稍后恢复', { exact: true }).click()
  await expect(page.getByText('恢复出题进度', { exact: true })).toBeVisible()
  completed = true; await page.reload()
  await page.getByText('恢复出题进度', { exact: true }).click()
  await expect(page.getByText('开始这一关', { exact: true })).toBeVisible()
  expect(preparations).toBe(1); expect(submitted).toBe(2); expect(new Set(keys).size).toBe(1)
})
test('纯网址读取失败不编造内容，明确主题说明可移交未核实范围', async ({ page }) => {
  let fallback = false
  await setup(page, path => {
    if (path === '/api/v1/materials/web') return { id: 'unreadable', status: 'running', stage: 'extracting' }
    if (path === '/api/v1/material-jobs/unreadable') return fallback ? { id: 'unreadable', status: 'succeeded', stage: 'succeeded', preparation_id: 'prep-1' } : { id: 'unreadable', status: 'failed', stage: 'failed', error_code: 'WEB_CONTENT_UNAVAILABLE', message: '无法读取网页，请粘贴正文或补充明确的学习主题' }
    if (path === '/api/v1/quiz/preparations/prep-1') return preparation({ grounding: { status: 'unverified' }, evidence: [] })
  })
  await start(page, 'https://example.org/unreadable')
  await page.getByText('读取网页内容', { exact: true }).click()
  await expect(page.getByText('暂时没能读懂材料', { exact: true })).toBeVisible()
  await expect(page.getByText('确认范围，生成关卡', { exact: true })).toHaveCount(0)
  await page.getByText('返回修改材料', { exact: true }).click()
  await page.getByLabel('网页学习说明').locator('input').fill('学习 AI 工程中的 Harness Engineering')
  fallback = true
  await page.getByText('读取网页内容', { exact: true }).click()
  await expect(page.getByText('未联网核实', { exact: true })).toBeVisible()
  await expect(page.getByText('选择学习主题（可多选）', { exact: true })).toBeVisible()
  await expect(page.getByText('预览学习资料', { exact: true })).toHaveCount(0)
})
test('准备取消释放原准备，迟到状态不会切回确认页面', async ({ page }) => {
  let cancelled = false
  await setup(page, path => {
    if (path.endsWith('/cancel')) { cancelled = true; return preparation({ status: 'cancelled', stage: 'cancelled' }) }
    if (path.startsWith('/api/v1/quiz/preparations')) return preparation({ status: 'running', stage: 'searching', content: null })
  })
  await start(page, 'Harness Engineering')
  await expect(page.getByText('正在搜索相关资料', { exact: true })).toBeVisible()
  await page.getByText('取消准备，返回首页', { exact: true }).click()
  await expect(page.locator('textarea')).toBeVisible()
  expect(cancelled).toBe(true)
  await expect(page.getByText('恢复范围准备', { exact: true })).toHaveCount(0)
})
test('提交时断网保留原键，重进后恢复生成', async ({ page }) => {
  const keys: string[] = []
  await setup(page)
  page.on('request', request => { if (new URL(request.url()).pathname === '/api/v1/quiz/generate') keys.push(request.headers()['idempotency-key']) })
  await page.route('**/api/v1/quiz/generate', route => route.abort())
  await start(page, 'Harness Engineering'); await select(page)
  await page.getByText('确认范围，生成关卡', { exact: true }).click()
  await expect(page.getByText('暂时没能完成', { exact: true })).toBeVisible()
  await page.getByText('返回首页', { exact: true }).click()
  await page.unroute('**/api/v1/quiz/generate')
  await page.reload()
  await page.getByText('恢复出题进度', { exact: true }).click()
  await expect(page.getByText('开始这一关', { exact: true })).toBeVisible()
  expect(keys).toHaveLength(2); expect(keys[1]).toBe(keys[0])
})
test('来源区分摘要、截断、页码与字幕，并可阅读外文长网址', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 568 })
  await setup(page, path => path.startsWith('/api/v1/quiz/preparations') ? preparation({ evidence: [
    { ...evidence[0], content_kind: 'snippet', truncated: true, context_truncated: true, url: 'https://example.org/' + 'long-reference/'.repeat(15) },
    { id: 'document', text: '文档原文片段', content_kind: 'material', page: 3 },
    { id: 'video', text: '字幕原文片段', content_kind: 'material', start: 92, end: 109 },
    { id: 'partial', text: '可读取的网页部分正文', content_kind: 'full_extract', acquisition_status: 'partial' },
  ] }) : undefined)
  await start(page, 'Harness Engineering')
  await page.getByText('预览学习资料', { exact: true }).click()
  await expect(page.getByText('搜索摘要', { exact: true })).toBeVisible()
  await expect(page.getByText('获取内容已截断 · 出题时仅使用其中部分内容', { exact: true })).toBeVisible()
  await expect(page.getByText('第 3 页', { exact: true })).toBeVisible()
  await expect(page.getByText('1:32 起', { exact: true })).toBeVisible()
  await expect(page.getByText('页面仅部分可读取', { exact: true })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.screenshot({ path: '../docs/quiz-grounding/screenshots/source-details-320.png' })
})


test('准备阶段回到规划或等待时，蓝色进度条不后退', async ({ page }) => {
  let stage = 'summarizing'
  await setup(page, path => path.startsWith('/api/v1/quiz/preparations') ? preparation({ status: 'running', stage, content: null }) : undefined)
  await start(page, 'Harness Engineering')
  const bar = page.locator('.generation-progress .weui-progress__inner-bar')
  await expect(bar).toHaveAttribute('style', /width: 70%/)
  for (const next of ['planning', 'waiting_rate_limit', 'extracting']) {
    stage = next
    await expect(page.locator('.generation-progress')).toContainText(next === 'planning' ? '正在规划资料获取' : next === 'waiting_rate_limit' ? '正在等待模型额度' : '正在读取网页正文', { timeout: 10000 })
    await expect(bar).toHaveAttribute('style', /width: 70%/)
  }
})
