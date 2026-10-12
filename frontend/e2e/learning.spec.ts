import { test, expect, Page } from '@playwright/test'
import fs from 'node:fs'
const sample = JSON.parse(fs.readFileSync('../backend/test-results/live-sample.json', 'utf8'))
const quiz = (count = 5) => ({
  ...sample.quiz,
  questions:
    count === 5
      ? sample.quiz.questions
      : [
          sample.quiz.questions.find((q: any) => q.type === 'single'),
          sample.quiz.questions.find((q: any) => q.type === 'multi'),
          sample.quiz.questions.find((q: any) => q.type === 'judge'),
        ],
})
const data = (p: Page) =>
  p.evaluate(() => JSON.parse(localStorage.getItem('levelup.local.v1') || 'null')?.data)
async function welcome(p: Page) {
  await p.goto('/')
  await p.getByText('先体验一关', { exact: true }).click()
  await expect(p.locator('textarea')).toBeVisible()
}
async function begin(p: Page, count = 5) {
  await p.route('**/api/v1/quiz/generate', (r) =>
    r.fulfill({ json: { code: 0, message: 'ok', data: quiz(count) } }),
  )
  await p.locator('textarea').fill('HTTP 为什么是无状态的？')
  if (count === 3) {
    await p.getByText('出题设置', { exact: false }).click()
    await p.getByText('3 题', { exact: true }).click()
  }
  await p.getByText('生成我的关卡', { exact: false }).click()
  await p.getByText('开始这一关', { exact: true }).click()
}
async function answer(p: Page, q: any, correct = true) {
  const selected = correct
    ? q.answers
    : [q.options.find((o: any) => !q.answers.includes(o.id))?.id || q.options[0].id]
  for (const id of selected)
    await p
      .locator('.option')
      .filter({ has: p.getByText(q.options.find((o: any) => o.id === id).text, { exact: true }) })
      .click()
  if (q.type === 'multi') await p.getByText('提交答案', { exact: true }).click()
  await expect(p.locator('.feedback')).toBeVisible()
}
async function next(p: Page, last = false) {
  await p.locator('.phone-bottom .btn').click()
  if (last) await expect(p.getByText('本轮正确率', { exact: true })).toBeVisible()
}

test('5 题闭环：全对、PNG 海报、重闯不重复奖励', async ({ page }) => {
  await welcome(page)
  await page.screenshot({ path: '../docs/implementation/screenshots/L20-390.png' })
  await begin(page)
  for (const [i, q] of quiz().questions.entries()) {
    await answer(page, q)
    if (i === 0) await page.screenshot({ path: '../docs/implementation/screenshots/L12-390.png' })
    await next(page, i === 4)
  }
  await expect(page.locator('.result-score')).toHaveText('100%')
  const before = await data(page)
  expect(before.sessions[0].answers).toHaveLength(5)
  await page.route('**/api/v1/report/generate', (r) =>
    r.fulfill({ json: { code: 0, message: 'ok', data: sample.report } }),
  )
  await page.getByText('看看这关学到了什么', { exact: true }).click()
  await page.getByText('分享这次收获', { exact: true }).click()
  await page.screenshot({ path: '../docs/implementation/screenshots/L18-390.png' })
  const download = page.waitForEvent('download')
  await page.getByText('保存海报图片', { exact: true }).click()
  const file = await download
  await file.saveAs('../docs/implementation/screenshots/generated-poster.png')
  expect(
    fs
      .readFileSync('../docs/implementation/screenshots/generated-poster.png')
      .subarray(1, 4)
      .toString(),
  ).toBe('PNG')
  await page.locator('.mini-back').click()
  await page.getByText('逐题回看', { exact: true }).click()
  await page.getByText('再闯一次这一关', { exact: true }).click()
  await page.getByText('开始这一关', { exact: true }).click()
  await answer(page, quiz().questions[0])
  const after = await data(page)
  expect(after.sessions[1].mode).toBe('replay')
  expect(after.sessions[0].answers).toHaveLength(5)
})
test('暂停、重启恢复锁定答案，离线完成，报告失败后重试', async ({ page }) => {
  await welcome(page)
  await begin(page, 3)
  const qs = quiz(3).questions
  await answer(page, qs[0], false)
  await page.locator('.mini-back').click()
  await expect(page.getByText('先歇一下？', { exact: true })).toBeVisible()
  await page.screenshot({ path: '../docs/implementation/screenshots/L14-390.png' })
  await page.getByText('保存进度并离开', { exact: true }).click()
  await page.reload()
  await page.getByText('继续', { exact: true }).click()
  await expect(page.locator('.feedback')).toBeVisible()
  await page.locator('.option').first().click()
  expect((await data(page)).sessions[0].answers).toHaveLength(1)
  await page.route('**/api/**', (r) => r.abort())
  await next(page)
  for (const [i, q] of qs.slice(1).entries()) {
    await answer(page, q)
    await next(page, i === 1)
  }
  await page.getByText('看看这关学到了什么', { exact: true }).click()
  await expect(page.getByText('重新试一次', { exact: true })).toBeVisible()
  expect((await data(page)).sessions[0].completed_at).toBeTruthy()
  await page.unroute('**/api/**')
  await page.route('**/api/v1/report/generate', (r) =>
    r.fulfill({ json: { code: 0, message: 'ok', data: sample.report } }),
  )
  await page.getByText('重新试一次', { exact: true }).click()
  await expect(page.getByText('三句话，带走这关', { exact: true })).toBeVisible()
  await page.getByText('前往个人学习中心', { exact: true }).click()
  await page.getByText('错题本', { exact: true }).click()
  await page.screenshot({ path: '../docs/implementation/screenshots/R08-390.png' })
  await page.getByText('开始复习', { exact: true }).click()
  await answer(page, qs[0])
  await next(page)
  await page.getByText('返回错题本', { exact: true }).click()
  await page.getByText('已掌握 1', { exact: true }).click()
  await expect(page.getByText(qs[0].stem, { exact: true })).toBeVisible()
})
test('320px 长文本、未开放弹窗与搜索空态无横向溢出', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 640 })
  await welcome(page)
  await page.locator('textarea').fill('理解一个很长的学习主题，'.repeat(200))
  await page.getByText('文档', { exact: true }).click()
  await expect(page.locator('.global-dialog')).toBeVisible()
  await page.getByText('知道了', { exact: true }).click()
  await page.screenshot({ path: '../docs/implementation/screenshots/L01-320.png' })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= 320)).toBe(true)
  await page.getByText('复盘', { exact: true }).click()
  await page.getByText('查看全部', { exact: true }).click()
  await page.locator('input').fill('没有此主题')
  await expect(page.getByText('已显示 0 条本机记录。', { exact: true })).toBeVisible()
})
test('真实后端：3 题生成、作答和报告接口联调', async ({ page }) => {
  test.setTimeout(180000)
  await welcome(page)
  await page.locator('textarea').fill('HTTP 为什么是无状态的？')
  await page.getByText('出题设置', { exact: false }).click()
  await page.getByText('3 题', { exact: true }).click()
  await page.getByText('生成我的关卡', { exact: false }).click()
  await page.getByText('开始这一关', { exact: true }).click({ timeout: 100000 })
  const q = (await data(page)).sessions[0].quiz
  for (const [i, x] of q.questions.entries()) {
    await answer(page, x, i !== 1)
    await next(page, i === 2)
  }
  await page.getByText('看看这关学到了什么', { exact: true }).click()
  await expect(page.getByText('三句话，带走这关', { exact: true })).toBeVisible({ timeout: 100000 })
  const d = await data(page)
  expect(d.sessions[0].report.stats.correct_count).toBe(2)
  await page.screenshot({ path: '../docs/implementation/screenshots/L17-real-390.png' })
})
