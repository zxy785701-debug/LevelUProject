# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: quiz-document.spec.ts >> 本题提交失败可重试，不重复提交已经确认的题目
- Location: e2e-accounts\quiz-document.spec.ts:121:5

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
- text: 0 XP 单选题 知识练习 第 1 个问题？
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
  25  |     if (request.method() === 'OPTIONS') { await route.fulfill({ headers, status: 204 }); return }
  26  |     if (pathname === '/api/v1/me') { await ok(user); return }
  27  |     if (pathname === '/api/v1/learning') { await ok({ version: 1, welcome: true, sessions: session ? [session] : [], activeId: session && !session.completed_at ? session.id : undefined, wrongs: {}, draft: { text: '', count: 5, difficulty: 'easy' } }); return }
  28  |     if (pathname === '/api/v1/quiz/preparations') { await ok({ id: 'preview-preparation', version: 1, status: 'ready', stage: 'ready', input_text: '知识练习', evidence: [], grounding: { status: 'unverified' }, content: { candidates: [{ id: 'c1', topic: '知识练习', domain: '基础知识', description: '预览', focuses: [{ id: 'f1', name: '基础概念', description: '预览', points: [{ id: 'p1', name: '知识点', evidence_ids: [], evidence_status: 'unverified' }] }] }] } }); return }
  29  |     if (pathname.startsWith('/api/v1/operations/')) { await ok({ status: 'succeeded', stage: 'succeeded', result: session }); return }
  30  |     if (pathname === '/api/v1/quiz/generate') {
  31  |       session = {
  32  |         id: 'preview-attempt', mode: 'new', cursor: 0, pending_ms: 0, started_at: new Date().toISOString(), answers: [],
  33  |         quiz: { id: 'preview-quiz', created_at: new Date().toISOString(), source_text: '知识练习', title: '知识练习', summary: '五道题', difficulty: 'easy', reward: { xp: 10, coins: 2 },
  34  |           questions: (['single', 'single', 'single', 'multi', 'judge'] as const).map((type, i) => ({ id: `q${i}`, type, stem: `第 ${i + 1} 个问题？`, options: (type === 'judge' ? ['A', 'B'] : ['A', 'B', 'C', 'D']).map(id => ({ id, text: `选项 ${id}` })), answers: type === 'multi' ? ['A', 'B'] : ['A'], explanation: '讲解', knowledge_point: '知识点' })) },
  35  |       }
  36  |       await ok({ kind: 'generation_operation', key: request.headers()['idempotency-key'], status: 'running', stage: 'generating', retry_after_seconds: 0, deadline: new Date(Date.now() + 300000).toISOString() }); return
  37  |     }
  38  |     if (request.method() === 'DELETE' && pathname === '/api/v1/attempts/preview-attempt') { session = undefined; await ok(user); return }
  39  |     if (pathname === '/api/v1/report/generate') { await new Promise(resolve => setTimeout(resolve, 1200)); await route.fulfill({ headers, status: 503, json: { code: 'TEMPORARY', message: '总结稍后重试' } }); return }
  40  |     if (pathname.endsWith('/progress') && session) { session.cursor = request.postDataJSON().cursor; await ok(session); return }
  41  |     if (pathname.endsWith('/answers') && session) {
  42  |       const answer = request.postDataJSON()
  43  |       answers.push(answer)
  44  |       if (answer.question_id === 'q1' && failOnce) { failOnce = false; await route.fulfill({ headers, status: 503, json: { code: 'TEMPORARY', message: '模拟提交中断' } }); return }
  45  |       if (!session.answers.some(a => a.question_id === answer.question_id)) {
  46  |         session.answers.push(answer)
  47  |         user.stats.xp += 10; user.stats.coins += 2
  48  |       }
  49  |       session.cursor = session.quiz.questions.findIndex(q => q.id === answer.question_id)
  50  |       if (session.answers.length === 5) session.completed_at = new Date().toISOString()
  51  |       await ok({ session, user }); return
  52  |     }
  53  |     if (pathname === '/api/v1/materials/document') { uploads.push(request.postData() || ''); await ok({ id: 'preview-job', status: 'running', stage: 'reading' }); return }
  54  |     if (pathname === '/api/v1/material-jobs/preview-job') { await ok({ id: 'preview-job', status: 'running', stage: 'reading' }); return }
  55  |     await route.fulfill({ headers, status: 404, json: { code: 'NOT_FOUND', message: pathname } })
  56  |   })
  57  |   await page.addInitScript(() => localStorage.setItem('levelup.auth.v1', JSON.stringify({ data: { token: 'preview-token' }, expire: null })))
  58  |   await page.goto('/')
  59  |   await expect(page.locator('textarea')).toBeVisible()
  60  |   await expect(page.getByText('正在同步云端学习记录…')).toHaveCount(0)
  61  |   return { answers, uploads }
  62  | }
  63  | 
  64  | async function startQuiz(page: Page) {
  65  |   await page.locator('textarea').fill('知识练习')
  66  |   await page.getByText('生成我的关卡', { exact: false }).click()
  67  |   await page.getByText('确认范围，生成关卡', { exact: true }).click()
  68  |   await page.getByText('开始这一关', { exact: true }).click()
  69  | }
  70  | 
  71  | test('逐题判分、多选确认、刷新保留，答完自动报告并返回首页、删除记录', async ({ page }, info) => {
  72  |   const api = await preview(page)
  73  |   await startQuiz(page)
  74  |   await page.locator('.option').first().click()
  75  |   await expect(page.locator('.feedback')).toBeVisible()
  76  |   await page.locator('.option').nth(1).click()
  77  |   expect(api.answers).toHaveLength(1)
  78  |   await page.locator('.mini-back').click()
  79  |   await page.getByText('保存进度并离开', { exact: true }).click()
  80  |   await page.reload()
  81  |   await page.getByText('继续', { exact: true }).click()
  82  |   await expect(page.locator('.feedback')).toBeVisible()
  83  |   await page.getByText('下一题', { exact: true }).click()
  84  |   for (let i = 1; i < 5; i++) {
  85  |     await expect(page.locator('.question')).toHaveText(`第 ${i + 1} 个问题？`)
  86  |     await page.locator('.option').first().click()
  87  |     if (i === 3) {
  88  |       await page.locator('.option').nth(1).click()
  89  |       await expect(page.locator('.feedback')).toHaveCount(0)
  90  |       expect(api.answers).toHaveLength(3)
  91  |       await page.getByText('确认本题', { exact: true }).click()
  92  |     }
  93  |     if (i < 4) {
  94  |       await expect(page.locator('.feedback')).toBeVisible()
  95  |       await page.getByText('下一题', { exact: true }).click()
  96  |     }
  97  |   }
  98  |   await expect(page.getByText('本轮学习报告', { exact: true })).toBeVisible()
  99  |   await expect(page.locator('.ring-value')).toHaveText('100%')
  100 |   await expect(page.getByText('本轮答案与解析', { exact: true })).toBeVisible()
  101 |   expect(api.answers.map(a => a.selected)).toEqual([['A'], ['A'], ['A'], ['A', 'B'], ['A']])
  102 |   await page.screenshot({ path: info.outputPath('instant-report.png') })
  103 |   await page.locator('.mini-back').click()
  104 |   await expect(page.locator('textarea')).toBeVisible()
  105 |   await page.waitForTimeout(1400)
  106 |   await expect(page.locator('textarea')).toBeVisible()
  107 |   await page.getByText('复盘', { exact: true }).click()
  108 |   await page.getByText('查看全部', { exact: true }).click()
  109 |   await page.getByText('删除学习记录', { exact: true }).click()
  110 |   await page.getByText('先保留', { exact: true }).click()
  111 |   await expect(page.locator('.history-entry')).toHaveCount(1)
  112 |   await page.getByText('删除学习记录', { exact: true }).click()
  113 |   await page.getByText('确认操作', { exact: true }).click()
  114 |   await expect(page.locator('.history-entry')).toHaveCount(0)
  115 |   await page.reload()
  116 |   await page.getByText('复盘', { exact: true }).click()
  117 |   await page.getByText('查看全部', { exact: true }).click()
  118 |   await expect(page.locator('.history-entry')).toHaveCount(0)
  119 | })
  120 | 
  121 | test('本题提交失败可重试，不重复提交已经确认的题目', async ({ page }) => {
  122 |   const api = await preview(page, true)
  123 |   await startQuiz(page)
  124 |   await page.locator('.option').first().click()
> 125 |   await expect(page.locator('.feedback')).toBeVisible()
      |                                           ^ Error: expect(locator).toBeVisible() failed
  126 |   await page.getByText('下一题', { exact: true }).click()
  127 |   await page.locator('.option').first().click()
  128 |   await expect(page.getByText('本题答案尚未确认', { exact: true })).toBeVisible()
  129 |   await expect(page.locator('.feedback')).toHaveCount(0)
  130 |   await page.getByText('确认操作', { exact: true }).click()
  131 |   await expect(page.locator('.feedback')).toBeVisible()
  132 |   expect(api.answers.filter(a => a.question_id === 'q0')).toHaveLength(1)
  133 |   expect(api.answers.filter(a => a.question_id === 'q1')).toHaveLength(2)
  134 | })
  135 | 
  136 | async function pickFile(page: Page, name: string) {
  137 |   const choosing = page.waitForEvent('filechooser')
  138 |   await page.getByText('点击选择一份文档', { exact: true }).click()
  139 |   await (await choosing).setFiles({ name, mimeType: name.endsWith('.pdf') ? 'application/pdf' : 'text/plain', buffer: Buffer.from('preview document') })
  140 | }
  141 | 
  142 | test('无文件可选页码，PDF 保留范围、校验错误就地提示并提交正确页码', async ({ page }, info) => {
  143 |   const api = await preview(page)
  144 |   await page.getByText('文档', { exact: true }).click()
  145 |   await expect(page.locator('.page-range')).toHaveCount(0)
  146 |   await page.getByText('指定页码', { exact: true }).click()
  147 |   const input = page.locator('.page-range input')
  148 |   await expect(input).toBeVisible()
  149 |   await input.fill('1,3-6')
  150 |   await expect(page.getByText('解析这份文档', { exact: true })).toHaveAttribute('disabled', '')
  151 |   for (const width of [390, 320]) {
  152 |     await page.setViewportSize({ width, height: 812 })
  153 |     expect(await page.locator('.page-range').evaluate(el => el.getBoundingClientRect().width)).toBeGreaterThan(250)
  154 |     expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  155 |     await page.screenshot({ path: info.outputPath(`document-pages-${width}.png`) })
  156 |   }
  157 |   await pickFile(page, 'notes.pdf')
  158 |   await expect(input).toHaveValue('1,3-6')
  159 |   await input.fill('6-2')
  160 |   await page.getByText('解析这份文档', { exact: true }).click()
  161 |   await expect(page.getByText('页码从 1 开始，结束页不能小于起始页')).toBeVisible()
  162 |   expect(api.uploads).toEqual([])
  163 |   await input.fill('1,3-6')
  164 |   await page.getByText('解析这份文档', { exact: true }).click()
  165 |   await expect.poll(() => api.uploads.length).toBe(1)
  166 |   expect(api.uploads[0]).toContain('1,3-6')
  167 | })
  168 | 
  169 | test('切换 TXT 自动使用全文并解释页码不可用', async ({ page }) => {
  170 |   await preview(page)
  171 |   await page.getByText('文档', { exact: true }).click()
  172 |   await page.getByText('指定页码', { exact: true }).click()
  173 |   await page.locator('.page-range input').fill('2-4')
  174 |   await pickFile(page, 'notes.txt')
  175 |   await expect(page.locator('.page-range')).toHaveCount(0)
  176 |   await expect(page.locator('.document-scope-option').first()).toHaveClass(/active/)
  177 |   await expect(page.getByText('DOCX 和 TXT 没有固定页码，已选择整份文档解析。')).toBeVisible()
  178 |   await expect(page.locator('.document-scope-option').last().locator('input')).toBeDisabled()
  179 |   await expect(page.locator('.page-range')).toHaveCount(0)
  180 |   await pickFile(page, 'notes.pdf')
  181 |   await page.getByText('指定页码', { exact: true }).click()
  182 |   await expect(page.locator('.page-range input')).toHaveValue('2-4')
  183 | })
  184 | 
```