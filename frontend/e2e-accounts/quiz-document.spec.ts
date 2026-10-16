import { apiOrigin, confirmedSession } from './runtime'
import { test, expect, Page } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'
import type { Session } from '../src/domain'

// Serve the built frontend and deterministic API responses without a database or AI calls.
async function preview(page: Page, failOnce = false) {
  let session: Session | undefined
  const answers: { question_id: string; selected: string[] }[] = []
  const uploads: string[] = []
  const user = { id: 'ui-preview', nickname: '学习搭子', avatar_version: 0, stats: { xp: 0, coins: 0, level: 1, topics: 0, streak: 0, accuracy: 0 }, quota: { remaining: 10, daily_limit: 10 } }
  const root = path.resolve('dist-h5')
  await page.route((process.env.LEVELUP_E2E_UI_ORIGIN || 'http://127.0.0.1:10086') + '/**', async route => {
    const pathname = new URL(route.request().url()).pathname
    const file = path.resolve(root, '.' + (pathname === '/' ? '/index.html' : pathname))
    if (!file.startsWith(root + path.sep) || !fs.existsSync(file)) { await route.fulfill({ status: 404 }); return }
    const type = { '.html': 'text/html', '.js': 'application/javascript', '.css': 'text/css', '.png': 'image/png' }[path.extname(file)] || 'application/octet-stream'
    await route.fulfill({ contentType: type, body: fs.readFileSync(file) })
  })
  await page.route('**/api/v1/**', async route => {
    const request = route.request(), pathname = new URL(request.url()).pathname
    const headers = { 'access-control-allow-origin': '*', 'access-control-allow-headers': '*', 'access-control-allow-methods': '*' }
    const ok = (data: unknown) => route.fulfill({ headers, json: { code: 0, data } })
    if (request.method() === 'OPTIONS') { await route.fulfill({ headers, status: 204 }); return }
    if (pathname === '/api/v1/me') { await ok(user); return }
    if (pathname === '/api/v1/learning') { await ok({ version: 1, welcome: true, sessions: session ? [session] : [], activeId: session && !session.completed_at ? session.id : undefined, wrongs: {}, draft: { text: '', count: 5, difficulty: 'easy' } }); return }
    if (pathname === '/api/v1/quiz/preparations') { await ok({ id: 'preview-preparation', version: 1, status: 'ready', stage: 'ready', input_text: '知识练习', evidence: [], grounding: { status: 'unverified' }, content: { candidates: [{ id: 'c1', topic: '知识练习', domain: '基础知识', description: '预览', focuses: [{ id: 'f1', name: '基础概念', description: '预览', points: [{ id: 'p1', name: '知识点', evidence_ids: [], evidence_status: 'unverified' }] }] }] } }); return }
    if (pathname.startsWith('/api/v1/operations/')) { await ok({ status: 'succeeded', stage: 'succeeded', result: session }); return }
    if (pathname === '/api/v1/quiz/generate') {
      session = {
        id: 'preview-attempt', mode: 'new', cursor: 0, pending_ms: 0, started_at: new Date().toISOString(), answers: [],
        quiz: { id: 'preview-quiz', created_at: new Date().toISOString(), source_text: '知识练习', title: '知识练习', summary: '五道题', difficulty: 'easy', reward: { xp: 10, coins: 2 },
          questions: (['single', 'single', 'single', 'multi', 'judge'] as const).map((type, i) => ({ id: `q${i}`, type, stem: `第 ${i + 1} 个问题？`, options: (type === 'judge' ? ['A', 'B'] : ['A', 'B', 'C', 'D']).map(id => ({ id, text: `选项 ${id}` })), answers: type === 'multi' ? ['A', 'B'] : ['A'], explanation: '讲解', knowledge_point: '知识点' })) },
      }
      await ok({ kind: 'generation_operation', key: request.headers()['idempotency-key'], status: 'running', stage: 'generating', retry_after_seconds: 0, deadline: new Date(Date.now() + 300000).toISOString() }); return
    }
    if (request.method() === 'DELETE' && pathname === '/api/v1/attempts/preview-attempt') { session = undefined; await ok(user); return }
    if (pathname === '/api/v1/report/generate') { await new Promise(resolve => setTimeout(resolve, 1200)); await route.fulfill({ headers, status: 503, json: { code: 'TEMPORARY', message: '总结稍后重试' } }); return }
    if (pathname.endsWith('/progress') && session) { session.cursor = request.postDataJSON().cursor; await ok(session); return }
    if (pathname.endsWith('/answers') && session) {
      const answer = request.postDataJSON()
      answers.push(answer)
      if (answer.question_id === 'q1' && failOnce) { failOnce = false; await route.fulfill({ headers, status: 503, json: { code: 'TEMPORARY', message: '模拟提交中断' } }); return }
      if (!session.answers.some(a => a.question_id === answer.question_id)) {
        session.answers.push(answer)
        user.stats.xp += 10; user.stats.coins += 2
      }
      session.cursor = session.quiz.questions.findIndex(q => q.id === answer.question_id)
      if (session.answers.length === 5) session.completed_at = new Date().toISOString()
      await ok({ session, user }); return
    }
    if (pathname === '/api/v1/materials/document') { uploads.push(request.postData() || ''); await ok({ id: 'preview-job', status: 'running', stage: 'reading' }); return }
    if (pathname === '/api/v1/material-jobs/preview-job') { await ok({ id: 'preview-job', status: 'running', stage: 'reading' }); return }
    await route.fulfill({ headers, status: 404, json: { code: 'NOT_FOUND', message: pathname } })
  })
  await page.addInitScript(() => localStorage.setItem('levelup.auth.v1', JSON.stringify({ data: { token: 'preview-token' }, expire: null })))
  await page.goto('/')
  await expect(page.locator('textarea')).toBeVisible()
  await expect(page.getByText('正在同步云端学习记录…')).toHaveCount(0)
  return { answers, uploads }
}

async function startQuiz(page: Page) {
  await page.locator('textarea').fill('知识练习')
  await page.getByText('生成我的关卡', { exact: false }).click()
  await page.getByText('确认范围，生成关卡', { exact: true }).click()
  await page.getByText('开始这一关', { exact: true }).click()
}

test('逐题判分、多选确认、刷新保留，答完自动报告并返回首页、删除记录', async ({ page }, info) => {
  const api = await preview(page)
  await startQuiz(page)
  await page.locator('.option').first().click()
  await expect(page.locator('.feedback')).toBeVisible()
  await page.locator('.option').nth(1).click()
  expect(api.answers).toHaveLength(1)
  await page.locator('.mini-back').click()
  await page.getByText('保存进度并离开', { exact: true }).click()
  await page.reload()
  await page.getByText('继续', { exact: true }).click()
  await expect(page.locator('.feedback')).toBeVisible()
  await page.getByText('下一题', { exact: true }).click()
  for (let i = 1; i < 5; i++) {
    await expect(page.locator('.question')).toHaveText(`第 ${i + 1} 个问题？`)
    await page.locator('.option').first().click()
    if (i === 3) {
      await page.locator('.option').nth(1).click()
      await expect(page.locator('.feedback')).toHaveCount(0)
      expect(api.answers).toHaveLength(3)
      await page.getByText('确认本题', { exact: true }).click()
    }
    if (i < 4) {
      await expect(page.locator('.feedback')).toBeVisible()
      await page.getByText('下一题', { exact: true }).click()
    }
  }
  await expect(page.getByText('本轮学习报告', { exact: true })).toBeVisible()
  await expect(page.locator('.ring-value')).toHaveText('100%')
  await expect(page.getByText('本轮答案与解析', { exact: true })).toBeVisible()
  expect(api.answers.map(a => a.selected)).toEqual([['A'], ['A'], ['A'], ['A', 'B'], ['A']])
  await page.screenshot({ path: info.outputPath('instant-report.png') })
  await page.locator('.mini-back').click()
  await expect(page.locator('textarea')).toBeVisible()
  await page.waitForTimeout(1400)
  await expect(page.locator('textarea')).toBeVisible()
  await page.getByText('复盘', { exact: true }).click()
  await page.getByText('查看全部', { exact: true }).click()
  await page.getByText('删除学习记录', { exact: true }).click()
  await page.getByText('先保留', { exact: true }).click()
  await expect(page.locator('.history-entry')).toHaveCount(1)
  await page.getByText('删除学习记录', { exact: true }).click()
  await page.getByText('确认操作', { exact: true }).click()
  await expect(page.locator('.history-entry')).toHaveCount(0)
  await page.reload()
  await page.getByText('复盘', { exact: true }).click()
  await page.getByText('查看全部', { exact: true }).click()
  await expect(page.locator('.history-entry')).toHaveCount(0)
})

test('本题提交失败可重试，不重复提交已经确认的题目', async ({ page }) => {
  const api = await preview(page, true)
  await startQuiz(page)
  await page.locator('.option').first().click()
  await expect(page.locator('.feedback')).toBeVisible()
  await page.getByText('下一题', { exact: true }).click()
  await page.locator('.option').first().click()
  await expect(page.getByText('本题答案尚未确认', { exact: true })).toBeVisible()
  await expect(page.locator('.feedback')).toHaveCount(0)
  await page.getByText('确认操作', { exact: true }).click()
  await expect(page.locator('.feedback')).toBeVisible()
  expect(api.answers.filter(a => a.question_id === 'q0')).toHaveLength(1)
  expect(api.answers.filter(a => a.question_id === 'q1')).toHaveLength(2)
})

async function pickFile(page: Page, name: string) {
  const choosing = page.waitForEvent('filechooser')
  await page.getByText('点击选择一份文档', { exact: true }).click()
  await (await choosing).setFiles({ name, mimeType: name.endsWith('.pdf') ? 'application/pdf' : 'text/plain', buffer: Buffer.from('preview document') })
}

test('无文件可选页码，PDF 保留范围、校验错误就地提示并提交正确页码', async ({ page }, info) => {
  const api = await preview(page)
  await page.getByText('文档', { exact: true }).click()
  await expect(page.locator('.page-range')).toHaveCount(0)
  await page.getByText('指定页码', { exact: true }).click()
  const input = page.locator('.page-range input')
  await expect(input).toBeVisible()
  await input.fill('1,3-6')
  await expect(page.getByText('解析这份文档', { exact: true })).toHaveAttribute('disabled', '')
  for (const width of [390, 320]) {
    await page.setViewportSize({ width, height: 812 })
    expect(await page.locator('.page-range').evaluate(el => el.getBoundingClientRect().width)).toBeGreaterThan(250)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await page.screenshot({ path: info.outputPath(`document-pages-${width}.png`) })
  }
  await pickFile(page, 'notes.pdf')
  await expect(input).toHaveValue('1,3-6')
  await input.fill('6-2')
  await page.getByText('解析这份文档', { exact: true }).click()
  await expect(page.getByText('页码从 1 开始，结束页不能小于起始页')).toBeVisible()
  expect(api.uploads).toEqual([])
  await input.fill('1,3-6')
  await page.getByText('解析这份文档', { exact: true }).click()
  await expect.poll(() => api.uploads.length).toBe(1)
  expect(api.uploads[0]).toContain('1,3-6')
})

test('切换 TXT 自动使用全文并解释页码不可用', async ({ page }) => {
  await preview(page)
  await page.getByText('文档', { exact: true }).click()
  await page.getByText('指定页码', { exact: true }).click()
  await page.locator('.page-range input').fill('2-4')
  await pickFile(page, 'notes.txt')
  await expect(page.locator('.page-range')).toHaveCount(0)
  await expect(page.locator('.document-scope-option').first()).toHaveClass(/active/)
  await expect(page.getByText('DOCX 和 TXT 没有固定页码，已选择整份文档解析。')).toBeVisible()
  await expect(page.locator('.document-scope-option').last().locator('input')).toBeDisabled()
  await expect(page.locator('.page-range')).toHaveCount(0)
  await pickFile(page, 'notes.pdf')
  await page.getByText('指定页码', { exact: true }).click()
  await expect(page.locator('.page-range input')).toHaveValue('2-4')
})
