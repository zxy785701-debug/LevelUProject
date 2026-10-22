# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: interactions.spec.ts >> 任意切题、草稿保留、未答完不出报告、进阶奖励与白色星星
- Location: e2e-accounts\interactions.spec.ts:26:5

# Error details

```
Error: expect(locator).toHaveCount(expected) failed

Locator:  locator('.feedback')
Expected: 0
Received: 1
Timeout:  5000ms

Call log:
  - Expect "toHaveCount" locator('.feedback') with timeout 5000ms
  - waiting for locator('.feedback')
    14 × locator resolved to 1 element
       - unexpected value "1"

```

# Page snapshot

```yaml
- generic [ref=f1e4]:
  - generic [ref=f1e5]: 9:41
  - generic [ref=f1e14]:
    - generic [ref=f1e15]: 本轮闯关
    - generic [ref=f1e20]: •••
  - generic [ref=f1e23]:
    - generic [ref=f1e24]:
      - generic [ref=f1e25]: 1 / 3
      - navigation "切换题目" [ref=f1e26]:
        - button "第 1 题" [ref=f1e27]:
          - generic [ref=f1e28]: "1"
        - button "第 2 题" [ref=f1e29]:
          - generic [ref=f1e30]: "2"
        - button "第 3 题" [ref=f1e31]:
          - generic [ref=f1e32]: "3"
      - generic [ref=f1e33]: 15 XP
    - generic [ref=f1e36]:
      - generic [ref=f1e37]: 单选题
      - generic [ref=f1e38]: HTTP 基础
    - generic [ref=f1e39]: 第 1 个问题？
    - generic [ref=f1e40]:
      - button "A 选项 A 正确" [ref=f1e41]:
        - generic [ref=f1e42]: A
        - generic [ref=f1e43]: 选项 A
        - generic [ref=f1e44]: 正确
      - button "B 选项 B 你的答案" [ref=f1e45]:
        - generic [ref=f1e46]: B
        - generic [ref=f1e47]: 选项 B
        - generic [ref=f1e48]: 你的答案
      - button "C 选项 C" [ref=f1e49]:
        - generic [ref=f1e50]: C
        - generic [ref=f1e51]: 选项 C
      - button "D 选项 D" [ref=f1e52]:
        - generic [ref=f1e53]: D
        - generic [ref=f1e54]: 选项 D
    - generic [ref=f1e55]:
      - generic [ref=f1e56]: 这题有个小转弯
      - generic [ref=f1e59]:
        - generic [ref=f1e60]: 正确答案：A
        - generic [ref=f1e61]: 说明原因与关键概念。
      - generic [ref=f1e62]:
        - generic [ref=f1e63]: 未联网核实
        - generic [ref=f1e64]: 学习范围：网络协议 · 综合学习所选主题，兼顾每个主题
        - generic [ref=f1e65]: 资料获取或支持不足，请结合可靠来源核对答案与讲解。
      - generic [ref=f1e66]: 本题没有可展示的支持片段，请结合可靠资料核对。
    - generic [ref=f1e67]: 已记入错题本，本题不获得奖励。
  - generic [ref=f1e68]:
    - generic [ref=f1e69]:
      - button "上一题" [disabled] [ref=f1e70] [cursor=pointer]
      - button "下一题" [ref=f1e71] [cursor=pointer]
    - generic [ref=f1e72]: 已答 2 / 3 题，答完自动查看报告
```

# Test source

```ts
  1   | import { apiOrigin, confirmedSession } from './runtime'
  2   | import { test, expect, Page, APIRequestContext } from '@playwright/test'
  3   | import fs from 'node:fs'
  4   | 
  5   | test.afterEach(async ({ page }) => { await page.unrouteAll({ behavior: 'wait' }) })
  6   | 
  7   | test.beforeEach(async ({ page }) => {
  8   |   await page.route('**/api/v1/**', async route => {
  9   |     const url = new URL(route.request().url()); url.port = new URL(apiOrigin).port
  10  |     await route.fulfill({ response: await route.fetch({ url: url.toString() }) })
  11  |   })
  12  | })
  13  | 
  14  | async function login(page: Page, request: APIRequestContext) {
  15  |   const response = await request.post(apiOrigin + '/api/v1/auth/wechat', { data: { code: `interactions-${Date.now()}-${Math.random()}`, agreement_version: '2026-10-12' } })
  16  |   expect(response.status()).toBe(200)
  17  |   const session = (await response.json()).data
  18  |   await page.goto('/')
  19  |   await page.evaluate(token => localStorage.setItem('levelup.auth.v1', JSON.stringify({ data: { token }, expire: null })), session.token)
  20  |   await page.reload()
  21  |   await expect(page.locator('textarea')).toBeVisible()
  22  |   await expect(page.getByText('正在同步云端学习记录…')).toHaveCount(0)
  23  |   return session
  24  | }
  25  | 
  26  | test('任意切题、草稿保留、未答完不出报告、进阶奖励与白色星星', async ({ page, request }) => {
  27  |   await login(page, request)
  28  |   await page.locator('textarea').fill('HTTP 为什么是无状态的？')
  29  |   const icon = await page.locator('.btn.primary .icon').getAttribute('src')
  30  |   expect(Buffer.from(icon!.split(',')[1], 'base64').equals(fs.readFileSync('src/assets/icons/spark-white.png'))).toBe(true)
  31  |   await expect(page.locator('.content > .row .xp')).toContainText('0 金币')
  32  |   await page.getByText('出题设置', { exact: false }).click()
  33  |   await page.getByText('3 题', { exact: true }).click()
  34  |   await page.getByText('进阶', { exact: true }).click()
  35  |   await page.getByText('生成我的关卡', { exact: false }).click()
  36  |   await page.getByText('确认范围，生成关卡', { exact: true }).click()
  37  |   await expect(page.getByText('每题首次答对 +15 XP、+3 金币；答错不扣已有奖励。')).toBeVisible()
  38  |   await page.getByText('开始这一关', { exact: true }).click()
  39  |   await expect(page.getByText('上一题', { exact: true })).toHaveAttribute('disabled', '')
  40  |   await page.locator('.quiz-step').nth(2).click()
  41  |   await expect(page.locator('.question')).toHaveText('第 3 个问题？')
  42  |   await page.locator('.option').nth(0).click()
  43  |   await expect(page.locator('.feedback')).toHaveCount(0)
  44  |   await page.locator('.option').nth(1).click()
  45  |   await expect(page.locator('.option').nth(1)).toHaveClass(/selected/)
  46  |   await page.locator('.option').nth(0).click()
  47  |   await page.getByText('确认本题', { exact: true }).click()
  48  |   await expect(page.locator('.feedback')).toBeVisible()
  49  |   await page.getByText('上一题', { exact: true }).click()
  50  |   await expect(page.locator('.question')).toHaveText('第 2 个问题？')
  51  |   await page.locator('.option').nth(0).click()
  52  |   await page.locator('.quiz-step').nth(0).click()
  53  |   await page.locator('.quiz-step').nth(1).click()
  54  |   await expect(page.locator('.option').nth(0)).toHaveClass(/selected/)
  55  |   await page.locator('.option').nth(1).click()
  56  |   await page.getByText('确认本题', { exact: true }).click()
  57  |   await expect(page.locator('.feedback')).toBeVisible()
  58  |   await page.locator('.quiz-step').nth(2).click()
  59  |   await expect(page.locator('.option').nth(0)).toHaveClass(/correct/)
  60  |   const buttons = await page.locator('.quiz-navigation .btn').evaluateAll(elements => elements.map(el => ({ top: el.getBoundingClientRect().top, height: el.getBoundingClientRect().height })))
  61  |   expect(Math.abs(buttons[0].top - buttons[1].top)).toBeLessThan(1)
  62  |   expect(Math.abs(buttons[0].height - buttons[1].height)).toBeLessThan(1)
  63  |   await page.locator('.quiz-step').nth(0).click()
  64  |   await page.locator('.option').nth(0).click()
> 65  |   await expect(page.locator('.feedback')).toHaveCount(0)
      |                                           ^ Error: expect(locator).toHaveCount(expected) failed
  66  |   await expect(page.locator('.ring-value')).toHaveCount(0)
  67  |   await page.getByText('确认本题', { exact: true }).click()
  68  |   await expect(page.locator('.ring-value')).toHaveText('100%')
  69  |   await expect(page.getByText('45', { exact: true })).toBeVisible()
  70  |   await expect(page.getByText('三句话，带走这关', { exact: true })).toBeVisible()
  71  | 
  72  | })
  73  | 
  74  | test('头像操作菜单、预览与实际图片下载', async ({ page, request }) => {
  75  |   const session = await login(page, request)
  76  |   const uploaded = await request.post(apiOrigin + '/api/v1/me/avatar', {
  77  |     headers: { Authorization: `Bearer ${session.token}` },
  78  |     multipart: { file: { name: 'avatar.png', mimeType: 'image/png', buffer: fs.readFileSync('src/assets/u-book.png') } },
  79  |   })
  80  |   expect(uploaded.status()).toBe(200)
  81  |   await page.reload()
  82  |   await page.getByText('我的', { exact: true }).click()
  83  |   await expect(page.locator('.profile-avatar-image')).toBeVisible()
  84  |   await page.locator('.profile-avatar').click()
  85  |   await expect(page.getByText('更换头像', { exact: true })).toHaveAttribute('open-type', 'chooseAvatar')
  86  |   await page.screenshot({ path: '../docs/quiz-grounding/account-screenshots/interactions-avatar-menu.png' })
  87  |   await page.getByText('查看头像', { exact: true }).click()
  88  |   await expect(page.locator('.avatar-preview-image')).toBeVisible()
  89  |   expect(await page.locator('.global-dialog').evaluate(el => Math.round(el.getBoundingClientRect().width))).toBe(390)
  90  |   await page.screenshot({ path: '../docs/quiz-grounding/account-screenshots/interactions-avatar-preview.png' })
  91  |   const downloading = page.waitForEvent('download')
  92  |   await page.getByText('保存头像图片', { exact: true }).click()
  93  |   const file = await downloading
  94  |   await file.saveAs('../docs/quiz-grounding/account-screenshots/interactions-avatar.jpg')
  95  |   expect(fs.readFileSync('../docs/quiz-grounding/account-screenshots/interactions-avatar.jpg').subarray(0, 2).toString('hex')).toBe('ffd8')
  96  |   await page.getByText('关闭', { exact: true }).click()
  97  |   await page.locator('.profile-avatar').click()
  98  |   await expect(page.getByText('更换头像', { exact: true })).toBeVisible()
  99  |   await page.getByText('取消', { exact: true }).click()
  100 | })
  101 | 
  102 | test('长页面进入历史再返回，恢复原滚动位置', async ({ page, request }) => {
  103 |   await page.setViewportSize({ width: 320, height: 560 })
  104 |   await login(page, request)
  105 |   await page.getByText('复盘', { exact: true }).click()
  106 |   const scroll = page.locator('.phone-scroll')
  107 |   await scroll.evaluate(element => { element.scrollTop = element.scrollHeight })
  108 |   await expect.poll(() => scroll.evaluate(element => element.scrollTop)).toBeGreaterThan(0)
  109 |   await page.waitForTimeout(200)
  110 |   const before = await scroll.evaluate(element => element.scrollTop)
  111 |   await page.getByText('查看全部', { exact: true }).click()
  112 |   await expect(page.getByText('这里，还没有学习记录')).toBeVisible()
  113 |   await page.locator('.mini-back').click()
  114 |   await expect(page.getByText('查看全部', { exact: true })).toBeVisible()
  115 |   await expect.poll(async () => Math.abs(await scroll.evaluate(element => element.scrollTop) - before)).toBeLessThan(3)
  116 |   expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  117 |   await page.screenshot({ path: '../docs/quiz-grounding/account-screenshots/interactions-scroll-return-320.png' })
  118 | })
  119 | 
```