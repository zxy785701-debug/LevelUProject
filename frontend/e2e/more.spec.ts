import { test, expect } from '@playwright/test'
import fs from 'node:fs'
const sample = JSON.parse(fs.readFileSync('../backend/test-results/live-sample.json', 'utf8'))
test('全部答错、真实分析、历史搜索、CSV 与本机数据操作', async ({ page }) => {
  await page.goto('/')
  await page.getByText('先体验一关', { exact: true }).click()
  await page.route('**/api/v1/quiz/generate', (r) =>
    r.fulfill({ json: { code: 0, message: 'ok', data: sample.quiz } }),
  )
  await page.locator('textarea').fill('HTTP 基础')
  await page.getByText('生成我的关卡', { exact: false }).click()
  await page.getByText('开始这一关', { exact: true }).click()
  for (const q of sample.quiz.questions) {
    const wrong = q.options.find((o: any) => !q.answers.includes(o.id)) || q.options[0]
    await page
      .locator('.option')
      .filter({ has: page.getByText(wrong.text, { exact: true }) })
      .click()
    if (q.type === 'multi') await page.getByText('提交答案', { exact: true }).click()
    await page.locator('.phone-bottom .btn').click()
  }
  await expect(page.locator('.result-score')).toHaveText('0%')
  await expect(page.getByText('+0 XP', { exact: true })).toBeVisible()
  await page.getByText('再学一个新主题', { exact: true }).click()
  await page.getByText('复盘', { exact: true }).click()
  await page.getByText('数据分析', { exact: true }).click()
  await expect(page.locator('.stat-grid')).toContainText('0%')
  await expect(page.locator('.chart-image')).toBeVisible()
  await page.screenshot({ path: '../docs/implementation/screenshots/R05-390.png' })
  await page.locator('.mini-back').click()
  await page.getByText('查看全部', { exact: true }).click()
  await page.locator('input').fill('HTTP')
  await expect(page.locator('.list-row')).toHaveCount(1)
  await page.locator('input').fill('不存在')
  await expect(page.locator('.list-row')).toHaveCount(0)
  await page.locator('.mini-back').click()
  await page.getByText('我的', { exact: true }).click()
  await page.screenshot({ path: '../docs/implementation/screenshots/A01-390.png' })
  // Navigate through the settings icon, as in the prototype.
  await page.locator('.settings-entry').click()
  await expect(page.getByText('按自己的节奏学', { exact: true })).toBeVisible()
  await page.screenshot({ path: '../docs/implementation/screenshots/A03-390.png' })
  const download = page.waitForEvent('download')
  await page.getByText('导出学习记录', { exact: true }).click()
  const file = await download
  await file.saveAs('../docs/implementation/screenshots/export.csv')
  const csv = fs.readFileSync('../docs/implementation/screenshots/export.csv', 'utf8')
  expect(csv).toContain(sample.quiz.title)
  expect(csv).toContain('你的答案')
  await page.getByText('数据与账户管理', { exact: true }).click()
  await page.getByText('清空待复习队列', { exact: true }).click()
  await page.getByText('确认操作', { exact: true }).click()
  const d = await page.evaluate(() => JSON.parse(localStorage.getItem('levelup.local.v1')!).data)
  expect(d.sessions[0].answers).toHaveLength(5)
  expect(Object.values(d.wrongs).every((w: any) => w.mastered)).toBe(true)
})
test('报告生成中离开，完成后保持当前页面', async ({ page }) => {
  await page.goto('/')
  await page.getByText('先体验一关', { exact: true }).click()
  await page.evaluate(
    ({ quiz }) => {
      localStorage.setItem(
        'levelup.local.v1',
        JSON.stringify({
          data: {
            version: 1,
            welcome: true,
            wrongs: {},
            draft: { text: '', count: 5, difficulty: 'easy' },
            activeId: 'done',
            sessions: [
              {
                id: 'done',
                quiz,
                mode: 'new',
                started_at: new Date().toISOString(),
                completed_at: new Date().toISOString(),
                cursor: 4,
                pending_ms: 0,
                answers: quiz.questions.map((q: any) => ({
                  question_id: q.id,
                  selected: q.answers,
                  elapsed_ms: 1000,
                })),
              },
            ],
          },
        }),
      )
    },
    { quiz: sample.quiz },
  )
  await page.reload()
  await page.getByText('复盘', { exact: true }).click()
  await page
    .locator('.list-row')
    .filter({ has: page.getByText(sample.quiz.title, { exact: true }) })
    .click()
  let finish: () => void = () => {}
  await page.route('**/api/v1/report/generate', async (r) => {
    await new Promise<void>((resolve) => {
      finish = resolve
    })
    await r.fulfill({ json: { code: 0, message: 'ok', data: sample.report } })
  })
  const requested = page.waitForRequest('**/api/v1/report/generate')
  await page.getByText('生成本轮复盘报告', { exact: true }).click()
  await requested
  await page.getByText('先去学习记录看看', { exact: true }).click()
  finish()
  await expect(page.getByText('每一次好奇，都有记录', { exact: true })).toBeVisible()
  await page.waitForTimeout(300)
  await expect(page.getByText('每一次好奇，都有记录', { exact: true })).toBeVisible()
})
