import { test, expect, Page } from '@playwright/test'

const points = Array.from({ length: 14 }, (_, i) => ({ id: 'p' + i, name: `请求验证知识点 ${i}`, total: 3, correct: 2, accuracy: 67, status: 'weak', attempt_ids: [], wrong_keys: [] }))
const names = ['FastAPI 特性学习范围 · 中等难度测验', 'Harness Engineering：智能体运行外壳与工具调用', 'LangGraph 概览学习检测', 'NMIXX 回归小测', '花儿与少年中文测验', '团队关系与冲突分析', '综合研读', '中国建交战略路径', '单片机代码运行基础', '莎士比亚基础知识', '骨折类型基础']
const tree = (count = 11) => ({ topics: Array.from({ length: count }, (_, i) => ({ id: 't' + String(i).padStart(4, '0'), name: names[i] || `扩展学习主题 ${i}`, points })), rule: '掌握度根据真实有效作答估计。' })
const analytics = { range: { start: '2026-10-10', end: '2026-10-16' }, totals: { total: 53, correct: 42, accuracy: 79, topics: 11, rounds: 11, duration_ms: 123000, learning_days: 5 }, trend: [], types: [] }
const report = { id: 'r1', status: 'succeeded', attempts: 2, created_at: new Date().toISOString(), snapshot: { sections: ['overview', 'performance', 'advice'], current: analytics, previous: { ...analytics, totals: { ...analytics.totals, total: 0, accuracy: null } }, knowledge: tree(), attempt_ids: [], provenance: [] }, content: { summary: ['继续用例子巩固知识。'], findings: [], suggestions: [] } }

async function setup(page: Page, count = 11, options: { failReport?: boolean; failPreview?: boolean } = {}) {
  let submits = 0
  const keys: string[] = []
  await page.addInitScript(() => localStorage.setItem('levelup.auth.v1', JSON.stringify({ data: { token: 'analysis-ui-test' }, expire: null })))
  await page.route('**/api/v1/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname
    let result: any
    if (path === '/api/v1/me') result = { id: 'ui-analysis', nickname: '学习者', avatar_version: 0, stats: { xp: 0, coins: 0, level: 1, topics: count, streak: 0, accuracy: 79 }, quota: { remaining: 10, daily_limit: 10 } }
    else if (path === '/api/v1/learning') result = { version: 1, sessions: [], wrongs: {}, welcome: true, draft: { text: '', count: 5, difficulty: 'easy' } }
    else if (path === '/api/v1/knowledge-map') result = tree(count)
    else if (path === '/api/v1/analytics') {
      if (options.failPreview) { await route.fulfill({ status: 503, json: { code: 'NETWORK_ERROR', message: '暂时无法读取学习记录' } }); return }
      result = analytics
    }
    else if (path === '/api/v1/period-reports') {
      if (request.method() === 'POST') {
        keys.push(request.headers()['idempotency-key']); submits++
        if (options.failReport && submits === 1) { await route.fulfill({ status: 502, json: { code: 'MODEL_INVALID_OUTPUT', message: 'AI 返回的内容未通过校验，请重试' } }); return }
        result = report
      } else result = submits ? [{ ...report, status: 'failed' }] : []
    } else throw new Error('Unexpected analysis request: ' + path)
    await route.fulfill({ json: { code: 0, data: result } })
  })
  await page.goto('/')
  await expect(page.locator('textarea')).toBeVisible()
  await page.getByText('复盘', { exact: true }).click()
  return keys
}

test('所有已学主题共用地图，搜索定位后展开知识点，缩放与回到中心可操作', async ({ page }) => {
  await setup(page)
  await page.getByText('知识地图', { exact: true }).click()
  await expect(page.locator('.atlas-node')).toHaveCount(11)
  await expect(page.locator('.atlas-edge')).toHaveCount(11)
  await expect(page.locator('.topic-atlas .chips')).toHaveCount(0)
  await expect(page.locator('.atlas-detail')).toHaveCount(0)
  await expect(page.locator('.atlas-viewport')).toHaveCSS('height', '360px')
  const viewport = await page.locator('.atlas-viewport').boundingBox(), hub = await page.locator('.atlas-hub').boundingBox()
  expect(Math.abs(hub!.x + hub!.width / 2 - viewport!.x - viewport!.width / 2)).toBeLessThan(3)
  expect(Math.abs(hub!.y + hub!.height / 2 - viewport!.y - viewport!.height / 2)).toBeLessThan(3)
  await page.screenshot({ path: '../docs/quiz-grounding/screenshots/knowledge-atlas-390.png' })
  const input = page.getByLabel('搜索学习主题或知识点').locator('input')
  await input.fill('Harness')
  await expect(page.locator('.atlas-search-result')).toHaveCount(1)
  await page.locator('.atlas-search-result').click()
  await expect(page.locator('.atlas-node.selected')).toBeInViewport()
  await expect(page.locator('.atlas-tools')).toContainText('100%')
  await page.setViewportSize({ width: 360, height: 812 })
  await expect(page.locator('.atlas-tools')).toContainText('100%')
  await page.setViewportSize({ width: 390, height: 812 })
  await expect(page.locator('.atlas-detail')).toContainText(names[1])
  await expect(page.locator('.atlas-detail .list-row')).toHaveCount(6)
  await page.locator('.atlas-detail').getByText('下一页', { exact: true }).click()
  await expect(page.locator('.atlas-detail')).toContainText('请求验证知识点 6')
  await page.getByLabel('放大知识地图').click()
  await expect(page.locator('.atlas-tools')).toContainText('125%')
  await page.getByLabel('缩小知识地图').click()
  await expect(page.locator('.atlas-tools')).toContainText('100%')
  await page.getByText('回到中心', { exact: true }).click()
  await expect(page.locator('.atlas-tools')).toContainText('60%')
  await expect(page.locator('.atlas-detail')).toHaveCount(0)
  await page.getByText('下个主题', { exact: true }).click()
  await expect(page.locator('.atlas-detail')).toContainText(names[0])
})

test('千个主题的小屏页面保持固定画布，搜索无长列表且能找到最外层主题', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 568 })
  await setup(page, 1000)
  await page.getByText('知识地图', { exact: true }).click()
  await expect(page.getByText('已连接 1000 个学习主题', { exact: true })).toBeVisible()
  await expect(page.locator('.atlas-node').first()).toBeAttached()
  expect(await page.locator('.atlas-node').count()).toBeLessThan(50)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await expect(page.locator('.atlas-viewport')).toHaveCSS('height', '360px')
  await page.getByLabel('搜索学习主题或知识点').locator('input').fill('学习')
  await expect(page.locator('.atlas-search-result')).toHaveCount(6)
  await page.getByLabel('搜索学习主题或知识点').locator('input').fill('扩展学习主题 999')
  await page.locator('.atlas-search-result').click()
  await expect(page.locator('.atlas-node.selected')).toBeInViewport()
  await expect(page.locator('.atlas-detail')).toContainText('扩展学习主题 999')
  await page.screenshot({ path: '../docs/quiz-grounding/screenshots/knowledge-atlas-1000-320.png' })
})

test('周期报告校验失败后可直接重试，成功进入报告且换用新请求键', async ({ page }) => {
  const keys = await setup(page, 11, { failReport: true })
  await page.getByText('数据分析', { exact: true }).click()
  await page.getByText('生成报告', { exact: true }).click()
  await page.getByText('生成这段时间的报告', { exact: true }).click()
  await expect(page.locator('.field-error')).toContainText('可直接重试生成')
  await expect(page.getByText('重新生成报告', { exact: true })).toBeEnabled()
  await page.screenshot({ path: '../docs/quiz-grounding/screenshots/period-retry-390.png' })
  await page.getByText('重新生成报告', { exact: true }).click()
  await expect(page.getByText('周期学习报告', { exact: true })).toBeVisible()
  await expect(page.getByText(report.content.summary[0], { exact: true })).toBeVisible()
  expect(keys).toHaveLength(2); expect(keys[0]).not.toBe(keys[1])
})

test('学习记录读取失败仍禁止生成，空地图没有多余主题列表', async ({ page }) => {
  await setup(page, 0, { failPreview: true })
  await page.getByText('知识地图', { exact: true }).click()
  await expect(page.getByText('知识地图，等你点亮', { exact: true })).toBeVisible()
  await expect(page.locator('.topic-atlas')).toHaveCount(0)
  await page.locator('.mini-back').click()
  await page.getByText('数据分析', { exact: true }).click()
  await page.getByText('生成报告', { exact: true }).click()
  await expect(page.locator('.field-error')).toContainText('暂时无法读取学习记录')
  await expect(page.getByText('生成这段时间的报告', { exact: true })).toHaveAttribute('disabled', '')
})

test('真实触摸可拖动与双指缩放，画布外页面不滚动，拖动不误开详情', async ({ page }) => {
  await setup(page)
  await page.getByText('知识地图', { exact: true }).click()
  await page.locator('.atlas-viewport').scrollIntoViewIfNeeded()
  const viewport = await page.locator('.atlas-viewport').boundingBox()
  const x = viewport!.x + viewport!.width / 2, y = viewport!.y + viewport!.height / 2
  const scroll = await page.locator('.phone-scroll').evaluate(el => el.scrollTop)
  const original = await page.locator('.atlas-hub').boundingBox()
  const cdp = await page.context().newCDPSession(page)
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x, y, id: 0 }] })
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: x + 60, y: y + 30, id: 0 }] })
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] })
  await expect.poll(async () => Math.round((await page.locator('.atlas-hub').boundingBox())!.x - original!.x)).toBe(60)
  expect(await page.locator('.phone-scroll').evaluate(el => el.scrollTop)).toBe(scroll)
  await expect(page.locator('.atlas-detail')).toHaveCount(0)
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x: x - 30, y, id: 0 }, { x: x + 30, y, id: 1 }] })
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: x - 60, y, id: 0 }, { x: x + 60, y, id: 1 }] })
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] })
  await expect(page.locator('.atlas-tools')).toContainText('120%')
  await page.getByText('回到中心', { exact: true }).click()
  await page.locator('.atlas-viewport').scrollIntoViewIfNeeded()
  const target = await page.locator('.atlas-node').first().boundingBox()
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x: target!.x + target!.width / 2, y: target!.y + target!.height / 2, id: 0 }] })
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] })
  await expect(page.locator('.atlas-detail')).toContainText(names[0])
})

