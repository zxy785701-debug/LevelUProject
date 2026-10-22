# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: accounts.spec.ts >> 暂停刷新恢复、断网不入账、错题复习不加奖励
- Location: e2e-accounts\accounts.spec.ts:82:5

# Error details

```
Error: expect(locator).toHaveText(expected) failed

Locator:  locator('.ring-value')
Expected: "67%"
Received: "33%"
Timeout:  5000ms

Call log:
  - Expect "toHaveText" locator('.ring-value') with timeout 5000ms
  - waiting for locator('.ring-value')
    11 × locator resolved to <taro-text-core class="ring-value">…</taro-text-core>
       - unexpected value "33%"

```

```yaml
- text: 33%
```

# Test source

```ts
  6   |     const url = new URL(route.request().url()); url.port = new URL(apiOrigin).port
  7   |     const response = await route.fetch({ url: url.toString() })
  8   |     await route.fulfill({ response })
  9   |   })
  10  | })
  11  | async function login(page: Page, request: APIRequestContext, code = `e2e-${Date.now()}-${Math.random()}`) {
  12  |   const response = await request.post(apiOrigin + '/api/v1/auth/wechat', { data: { code, agreement_version: '2026-10-12' } })
  13  |   expect(response.status()).toBe(200)
  14  |   const session = (await response.json()).data
  15  |   await page.goto('/')
  16  |   await page.evaluate(token => localStorage.setItem('levelup.auth.v1', JSON.stringify({ data: { token }, expire: null })), session.token)
  17  |   await page.reload()
  18  |   await expect(page.locator('textarea')).toBeVisible()
  19  |   await expect(page.getByText('正在同步云端学习记录…')).toHaveCount(0)
  20  |   return session
  21  | }
  22  | async function begin(page: Page, count = 3) {
  23  |   await page.locator('textarea').fill('HTTP 为什么是无状态的？')
  24  |   if (count === 3) { await page.getByText('出题设置', { exact: false }).click(); await page.getByText('3 题', { exact: true }).click() }
  25  |   await page.getByText('生成我的关卡', { exact: false }).click()
  26  |   await page.getByText('确认范围，生成关卡', { exact: true }).click()
  27  |   await page.getByText('开始这一关', { exact: true }).click()
  28  | }
  29  | async function answer(page: Page, index: number, correct = true, last = false) {
  30  |   await expect(page.locator('.question')).toHaveText(`第 ${index + 1} 个问题？`)
  31  |   const multi = index === 1
  32  |   const selected = correct ? (multi ? [0, 1] : [0]) : [1]
  33  |   for (const i of selected) await page.locator('.option').nth(i).click()
  34  |   await page.getByText('确认本题', { exact: true }).click()
  35  |   if (last) await expect(page.locator('.ring-value')).toBeVisible()
  36  |   else { await expect(page.locator('.feedback')).toBeVisible(); await page.getByText('下一题', { exact: true }).click(); await expect(page.locator('.question')).toHaveText(`第 ${index + 2} 个问题？`) }
  37  | }
  38  | test('未登录强制登录，无游客入口；320px 布局', async ({ page }) => {
  39  |   await page.setViewportSize({ width: 320, height: 640 })
  40  |   await page.goto('/')
  41  |   await expect(page.getByText('保存你的学习旅程', { exact: true })).toBeVisible()
  42  |   await expect(page.locator('textarea')).toHaveCount(0)
  43  |   await expect(page.getByText('暂不登录，先体验', { exact: true })).toHaveCount(0)
  44  |   const loginButton = page.locator('.phone-bottom .btn')
  45  |   await expect(loginButton).toHaveAttribute('disabled', '')
  46  |   await expect(loginButton).toHaveCSS('background-color', 'rgb(237, 240, 245)')
  47  |   await page.locator('taro-checkbox-core').click()
  48  |   await expect(loginButton).not.toHaveAttribute('disabled', '')
  49  |   await page.locator('taro-checkbox-core').click()
  50  |   await expect(loginButton).toHaveAttribute('disabled', '')
  51  |   await expect(loginButton).toHaveCSS('background-color', 'rgb(237, 240, 245)')
  52  |   await page.locator('.phone-scroll').evaluate(element => { element.scrollTop = 0 })
  53  |   expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
  54  |   await page.screenshot({ path: '../docs/quiz-grounding/account-screenshots/A02-320.png' })
  55  | })
  56  | test('真实 MySQL 闭环：答题、报告、海报、昵称、退出', async ({ page, request }) => {
  57  |   await login(page, request)
  58  |   await begin(page)
  59  |   for (let i = 0; i < 3; i++) await answer(page, i, true, i === 2)
  60  |   await expect(page.locator('.ring-value')).toHaveText('100%')
  61  |   await expect(page.getByText('三句话，带走这关', { exact: true })).toBeVisible()
  62  |   await page.getByText('分享这次收获', { exact: true }).click()
  63  |   const download = page.waitForEvent('download')
  64  |   await page.getByText('保存海报图片', { exact: true }).click()
  65  |   const file = await download
  66  |   await file.saveAs('../docs/quiz-grounding/account-screenshots/learning-poster.png')
  67  |   expect(fs.readFileSync('../docs/quiz-grounding/account-screenshots/learning-poster.png').subarray(1, 4).toString()).toBe('PNG')
  68  |   await page.reload()
  69  |   await page.getByText('我的', { exact: true }).click()
  70  |   await expect(page.getByText('6', { exact: true })).toBeVisible()
  71  |   await page.getByText('好奇心同学', { exact: true }).click()
  72  |   await page.locator('input[name="nickname"]').fill('云端学习者')
  73  |   await page.getByText('保存昵称', { exact: true }).click()
  74  |   await expect(page.getByText('云端学习者', { exact: true })).toBeVisible()
  75  |   await page.screenshot({ path: '../docs/quiz-grounding/account-screenshots/A01-390.png' })
  76  |   await page.locator('.settings-entry').click()
  77  |   await page.getByText('数据与账户管理', { exact: true }).click()
  78  |   await page.getByText('退出登录', { exact: true }).click()
  79  |   await page.getByText('确认操作', { exact: true }).click()
  80  |   await expect(page.getByText('保存你的学习旅程', { exact: true })).toBeVisible()
  81  | })
  82  | test('暂停刷新恢复、断网不入账、错题复习不加奖励', async ({ page, request }) => {
  83  |   const session = await login(page, request)
  84  |   await begin(page)
  85  |   await page.locator('.option').nth(1).click()
  86  |   await page.getByText('确认本题', { exact: true }).click()
  87  |   await expect(page.locator('.feedback')).toBeVisible()
  88  |   await page.locator('.mini-back').click()
  89  |   await page.getByText('保存进度并离开', { exact: true }).click()
  90  |   await page.reload()
  91  |   await page.getByText('继续', { exact: true }).click()
  92  |   await expect(page.locator('.option').nth(1)).toHaveClass(/incorrect/)
  93  |   await page.getByText('下一题', { exact: true }).click()
  94  |   await page.locator('.option').nth(0).click()
  95  |   await page.locator('.option').nth(1).click()
  96  |   await page.getByText('确认本题', { exact: true }).click()
  97  |   await expect(page.locator('.feedback')).toBeVisible()
  98  |   await page.getByText('下一题', { exact: true }).click()
  99  |   await page.route('**/attempts/*/answers', route => route.abort())
  100 |   await page.locator('.option').nth(0).click()
  101 |   await page.getByText('确认本题', { exact: true }).click()
  102 |   await expect(page.getByText('本题答案尚未确认', { exact: true })).toBeVisible()
  103 |   await expect(page.locator('.feedback')).toHaveCount(0)
  104 |   await page.unroute('**/attempts/*/answers')
  105 |   await page.getByText('确认操作', { exact: true }).click()
> 106 |   await expect(page.locator('.ring-value')).toHaveText('67%')
      |                                             ^ Error: expect(locator).toHaveText(expected) failed
  107 |   await expect(page.getByText('三句话，带走这关', { exact: true })).toBeVisible()
  108 |   const headers = { Authorization: `Bearer ${session.token}` }
  109 |   const before = (await (await request.get(apiOrigin + '/api/v1/me', { headers })).json()).data.stats.xp
  110 |   await page.locator('.mini-back').click()
  111 |   await page.getByText('复盘', { exact: true }).click()
  112 |   await page.getByText('错题本', { exact: true }).click()
  113 |   await page.getByText('开始复习', { exact: true }).click()
  114 |   await page.locator('.option').nth(0).click()
  115 |   await page.getByText('确认本题', { exact: true }).click()
  116 |   await expect(page.getByText('本轮学习报告', { exact: true })).toBeVisible()
  117 |   expect((await (await request.get(apiOrigin + '/api/v1/me', { headers })).json()).data.stats.xp).toBe(before)
  118 |   await page.locator('.mini-back').click()
  119 |   await page.getByText('复盘', { exact: true }).click()
  120 |   await page.getByText('错题本', { exact: true }).click()
  121 |   await page.getByText('已掌握 1', { exact: true }).click()
  122 |   await expect(page.getByText('第 1 个问题？', { exact: true })).toBeVisible()
  123 | })
  124 | 
  125 | test('账号隔离与过期回登录', async ({ page, request }) => {
  126 |   const first = await login(page, request)
  127 |   await begin(page)
  128 |   await page.reload()
  129 |   const other = await request.post(apiOrigin + '/api/v1/auth/wechat', { data: { code: `other-${Date.now()}`, agreement_version: '2026-10-12' } })
  130 |   const second = (await other.json()).data
  131 |   await page.evaluate(token => localStorage.setItem('levelup.auth.v1', JSON.stringify({ data: { token }, expire: null })), second.token)
  132 |   await page.reload()
  133 |   await expect(page.locator('textarea')).toBeVisible()
  134 |   await expect(page.getByText('继续', { exact: true })).toHaveCount(0)
  135 |   await request.post(apiOrigin + '/api/v1/auth/logout', { headers: { Authorization: `Bearer ${second.token}` } })
  136 |   await page.reload()
  137 |   await expect(page.getByText('保存你的学习旅程', { exact: true })).toBeVisible()
  138 | })
  139 | 
```