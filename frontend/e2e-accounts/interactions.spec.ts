import { apiOrigin, confirmedSession } from './runtime'
import { test, expect, Page, APIRequestContext } from '@playwright/test'
import fs from 'node:fs'

test.afterEach(async ({ page }) => { await page.unrouteAll({ behavior: 'wait' }) })

test.beforeEach(async ({ page }) => {
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url()); url.port = new URL(apiOrigin).port
    await route.fulfill({ response: await route.fetch({ url: url.toString() }) })
  })
})

async function login(page: Page, request: APIRequestContext) {
  const response = await request.post(apiOrigin + '/api/v1/auth/wechat', { data: { code: `interactions-${Date.now()}-${Math.random()}`, agreement_version: '2026-10-12' } })
  expect(response.status()).toBe(200)
  const session = (await response.json()).data
  await page.goto('/')
  await page.evaluate(token => localStorage.setItem('levelup.auth.v1', JSON.stringify({ data: { token }, expire: null })), session.token)
  await page.reload()
  await expect(page.locator('textarea')).toBeVisible()
  await expect(page.getByText('正在同步云端学习记录…')).toHaveCount(0)
  return session
}

test('任意切题、草稿保留、未答完不出报告、进阶奖励与白色星星', async ({ page, request }) => {
  await login(page, request)
  await page.locator('textarea').fill('HTTP 为什么是无状态的？')
  const icon = await page.locator('.btn.primary .icon').getAttribute('src')
  expect(Buffer.from(icon!.split(',')[1], 'base64').equals(fs.readFileSync('src/assets/icons/spark-white.png'))).toBe(true)
  await expect(page.locator('.content > .row .xp')).toContainText('0 金币')
  await page.getByText('出题设置', { exact: false }).click()
  await page.getByText('3 题', { exact: true }).click()
  await page.getByText('进阶', { exact: true }).click()
  await page.getByText('生成我的关卡', { exact: false }).click()
  await page.getByText('确认范围，生成关卡', { exact: true }).click()
  await expect(page.getByText('每题首次答对 +15 XP、+3 金币；答错不扣已有奖励。')).toBeVisible()
  await page.getByText('开始这一关', { exact: true }).click()
  await expect(page.getByText('上一题', { exact: true })).toHaveAttribute('disabled', '')
  await page.locator('.quiz-step').nth(2).click()
  await expect(page.locator('.question')).toHaveText('第 3 个问题？')
  await page.locator('.option').nth(0).click()
  await expect(page.locator('.feedback')).toHaveCount(0)
  await page.locator('.option').nth(1).click()
  await expect(page.locator('.option').nth(1)).toHaveClass(/selected/)
  await page.locator('.option').nth(0).click()
  await page.getByText('确认本题', { exact: true }).click()
  await expect(page.locator('.feedback')).toBeVisible()
  await page.getByText('上一题', { exact: true }).click()
  await expect(page.locator('.question')).toHaveText('第 2 个问题？')
  await page.locator('.option').nth(0).click()
  await page.locator('.quiz-step').nth(0).click()
  await page.locator('.quiz-step').nth(1).click()
  await expect(page.locator('.option').nth(0)).toHaveClass(/selected/)
  await page.locator('.option').nth(1).click()
  await page.getByText('确认本题', { exact: true }).click()
  await expect(page.locator('.feedback')).toBeVisible()
  await page.locator('.quiz-step').nth(2).click()
  await expect(page.locator('.option').nth(0)).toHaveClass(/correct/)
  const buttons = await page.locator('.quiz-navigation .btn').evaluateAll(elements => elements.map(el => ({ top: el.getBoundingClientRect().top, height: el.getBoundingClientRect().height })))
  expect(Math.abs(buttons[0].top - buttons[1].top)).toBeLessThan(1)
  expect(Math.abs(buttons[0].height - buttons[1].height)).toBeLessThan(1)
  await page.locator('.quiz-step').nth(0).click()
  await page.locator('.option').nth(0).click()
  await expect(page.locator('.feedback')).toHaveCount(0)
  await expect(page.locator('.ring-value')).toHaveCount(0)
  await page.getByText('确认本题', { exact: true }).click()
  await expect(page.locator('.ring-value')).toHaveText('100%')
  await expect(page.getByText('45', { exact: true })).toBeVisible()
  await expect(page.getByText('三句话，带走这关', { exact: true })).toBeVisible()

})

test('头像操作菜单、预览与实际图片下载', async ({ page, request }) => {
  const session = await login(page, request)
  const uploaded = await request.post(apiOrigin + '/api/v1/me/avatar', {
    headers: { Authorization: `Bearer ${session.token}` },
    multipart: { file: { name: 'avatar.png', mimeType: 'image/png', buffer: fs.readFileSync('src/assets/u-book.png') } },
  })
  expect(uploaded.status()).toBe(200)
  await page.reload()
  await page.getByText('我的', { exact: true }).click()
  await expect(page.locator('.profile-avatar-image')).toBeVisible()
  await page.locator('.profile-avatar').click()
  await expect(page.getByText('更换头像', { exact: true })).toHaveAttribute('open-type', 'chooseAvatar')
  await page.screenshot({ path: '../docs/quiz-grounding/account-screenshots/interactions-avatar-menu.png' })
  await page.getByText('查看头像', { exact: true }).click()
  await expect(page.locator('.avatar-preview-image')).toBeVisible()
  expect(await page.locator('.global-dialog').evaluate(el => Math.round(el.getBoundingClientRect().width))).toBe(390)
  await page.screenshot({ path: '../docs/quiz-grounding/account-screenshots/interactions-avatar-preview.png' })
  const downloading = page.waitForEvent('download')
  await page.getByText('保存头像图片', { exact: true }).click()
  const file = await downloading
  await file.saveAs('../docs/quiz-grounding/account-screenshots/interactions-avatar.jpg')
  expect(fs.readFileSync('../docs/quiz-grounding/account-screenshots/interactions-avatar.jpg').subarray(0, 2).toString('hex')).toBe('ffd8')
  await page.getByText('关闭', { exact: true }).click()
  await page.locator('.profile-avatar').click()
  await expect(page.getByText('更换头像', { exact: true })).toBeVisible()
  await page.getByText('取消', { exact: true }).click()
})

test('长页面进入历史再返回，恢复原滚动位置', async ({ page, request }) => {
  await page.setViewportSize({ width: 320, height: 560 })
  await login(page, request)
  await page.getByText('复盘', { exact: true }).click()
  const scroll = page.locator('.phone-scroll')
  await scroll.evaluate(element => { element.scrollTop = element.scrollHeight })
  await expect.poll(() => scroll.evaluate(element => element.scrollTop)).toBeGreaterThan(0)
  await page.waitForTimeout(200)
  const before = await scroll.evaluate(element => element.scrollTop)
  await page.getByText('查看全部', { exact: true }).click()
  await expect(page.getByText('这里，还没有学习记录')).toBeVisible()
  await page.locator('.mini-back').click()
  await expect(page.getByText('查看全部', { exact: true })).toBeVisible()
  await expect.poll(async () => Math.abs(await scroll.evaluate(element => element.scrollTop) - before)).toBeLessThan(3)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({ path: '../docs/quiz-grounding/account-screenshots/interactions-scroll-return-320.png' })
})
