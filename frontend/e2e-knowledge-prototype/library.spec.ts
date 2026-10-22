import { test, expect, Page } from '@playwright/test'
import fs from 'node:fs'
const screenshots = '../docs/knowledge-prototype/screenshots'
fs.mkdirSync(screenshots, { recursive: true })
const runtimeErrors = new WeakMap<Page, string[]>()
test.beforeEach(async ({ page }) => {
  const errors: string[] = []
  runtimeErrors.set(page, errors)
  page.on('pageerror', (e) => errors.push(e.message))
})
test.afterEach(async ({ page }) => expect(runtimeErrors.get(page) || []).toEqual([]))
const now = new Date().toISOString()
const docs = [
  ['d1', 'HTTP 学习笔记.pdf', 'pdf', 'ready'],
  ['d2', 'HTTP 缓存机制.md', 'md', 'ready'],
  ['d3', 'JavaScript 闭包笔记.pdf', 'pdf', 'ready'],
  ['d4', '网络基础课程', 'web', 'processing'],
].map(([id, title, source_type, status]) => ({
  id,
  title,
  source_type,
  status,
  source: {
    filename: title,
    ...(source_type === 'web' ? { url: 'https://example.org/course' } : {}),
  },
  active_revision_id: status === 'ready' ? 'v1' : null,
  version: status === 'ready' ? 1 : null,
  text_chars: 300,
  chunk_count: status === 'ready' ? 3 : 0,
  created_at: now,
  updated_at: now,
}))
const chunks = [
  'HTTP 是无状态协议；这意味着服务器不会在两个请求之间保留状态。',
  '网站通常使用 HTTP Cookie 建立会话。Cookie 在客户端携带会话标识。',
  'Session 在服务端保存会话信息。',
].map((text, position) => ({
  id: 'c' + position,
  revision_id: 'v1',
  position,
  text,
  location: {
    page: 3 + position,
    header_path: [['HTTP 无状态'], ['Cookie'], ['Session']][position],
    start_index: position * 100,
    end_index: position * 100 + text.length,
  },
}))
const point = { id: 'p1', name: 'HTTP 无状态', evidence_ids: ['s1'], evidence_status: 'available' }
const candidates = ['HTTP 的无状态与会话', 'Cookie 与 Session 的区别'].map((topic, i) => ({
  id: 'topic-' + i,
  topic,
  domain: '计算机基础',
  description: i ? '学习 Cookie 与 Session 的职责。' : '从协议特性，到 Cookie 与 Session 的区别。',
  focuses: [{ id: 'focus-' + i, name: topic, description: topic, points: [point] }],
}))
const scope = {
  kind: 'knowledge_scope',
  id: 'scope-1',
  version: 1,
  goal: '理解 HTTP 无状态与会话',
  input_text: '理解 HTTP 无状态与会话',
  status: 'ready',
  supplement: true,
  documents: docs.slice(0, 2).map((d) => ({ ...d, revision_id: 'v1' })),
  content: { candidates },
  evidence: [{ id: 's1', text: chunks[0].text, title: docs[0].title, content_kind: 'material' }],
  grounding: { status: 'material_only' },
  recommended_candidate_ids: ['topic-0'],
  created_at: now,
  expires_at: new Date(Date.now() + 86400000).toISOString(),
}
async function setup(page: Page) {
  const mutations: string[] = []
  await page.addInitScript(
    ({ now }) => {
      if (!sessionStorage.getItem('kb-prototype-seeded')) {
        localStorage.setItem(
          'levelup.auth.v1',
          JSON.stringify({ data: { token: 'prototype-a' }, expire: null }),
        )
        const folderState = {
          version: 1,
          owner: 'prototype-a',
          folders: ['计算机基础', '读书笔记', '工作学习手册'].map((name, i) => ({
            id: 'f' + i,
            name,
            description: i === 0 ? '网络、操作系统和编程基础。' : '',
            createdAt: Date.parse(now),
            updatedAt: Date.parse(now),
          })),
          assignments: { d1: 'f0', d2: 'f0', d3: 'f0', d4: 'f0' },
          recent: { d1: Date.parse(now) + 10 },
        }
        localStorage.setItem(
          'levelup.knowledge.folders.v1:prototype-a',
          JSON.stringify({ data: folderState, expire: null }),
        )
        localStorage.setItem(
          'levelup.knowledge.draft.v1:prototype-a',
          JSON.stringify({
            data: {
              text: '理解 HTTP 无状态与会话',
              ids: ['d1', 'd2'],
              all: false,
              supplement: true,
            },
            expire: null,
          }),
        )
        sessionStorage.setItem('kb-prototype-seeded', '1')
      }
      const removeOverlay = () =>
        document.getElementById('webpack-dev-server-client-overlay')?.remove()
      document.addEventListener('DOMContentLoaded', () =>
        new MutationObserver(removeOverlay).observe(document.documentElement, {
          childList: true,
          subtree: true,
        }),
      )
    },
    { now },
  )
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request(),
      path = new URL(request.url()).pathname,
      account = request.headers().authorization?.includes('prototype-b')
        ? 'prototype-b'
        : 'prototype-a'
    if (request.method() !== 'GET') mutations.push(request.method() + ' ' + path)
    let data: any
    if (path === '/api/v1/me')
      data = {
        id: account,
        nickname: '学习者',
        avatar_version: 0,
        stats: { xp: 0, coins: 0, level: 1, topics: 0, streak: 0, accuracy: 0 },
        quota: { remaining: 10, daily_limit: 10 },
      }
    else if (path === '/api/v1/learning')
      data = {
        version: 1,
        sessions: [],
        wrongs: {},
        welcome: true,
        draft: { text: '', count: 3, difficulty: 'easy' },
      }
    else if (path.endsWith('/knowledge/capabilities'))
      data = {
        enabled: true,
        available: true,
        web_available: true,
        limits: { max_bytes: 20971520, max_documents: 100 },
        disclosure: '文件保存在服务端，正文发送百炼向量化，检索片段发送 DeepSeek。',
      }
    else if (path.endsWith('/knowledge/documents'))
      data = {
        items: account === 'prototype-a' ? docs : [],
        total: account === 'prototype-a' ? docs.length : 0,
        page: 1,
        page_size: 100,
      }
    else if (path.endsWith('/knowledge/documents/d1/chunks'))
      data = { items: chunks, total: chunks.length, page: 1, page_size: 20 }
    else if (path.endsWith('/knowledge/documents/d1')) data = docs[0]
    else if (path.endsWith('/knowledge/quiz-preparations') && request.method() === 'POST')
      data = {
        kind: 'knowledge_job',
        job_type: 'prepare',
        id: 'job1',
        job_id: 'job1',
        status: 'queued',
        stage: 'queued',
        progress: 0,
        deadline: new Date(Date.now() + 240000).toISOString(),
        created_at: now,
        retry_after_seconds: 0,
      }
    else if (path.endsWith('/knowledge/jobs/job1'))
      data = {
        kind: 'knowledge_job',
        job_type: 'prepare',
        id: 'job1',
        job_id: 'job1',
        status: 'succeeded',
        stage: 'succeeded',
        progress: 100,
        deadline: new Date(Date.now() + 240000).toISOString(),
        created_at: now,
        retry_after_seconds: 0,
        result: { scope_id: scope.id },
      }
    else if (path.endsWith('/knowledge/quiz-preparations/scope-1')) data = scope
    else throw new Error('Unexpected request: ' + request.method() + ' ' + path)
    await route.fulfill({ json: { code: 0, data } })
  })
  await page.goto('/')
  await expect(page.locator('textarea')).toBeVisible()
  await page.getByText('我的', { exact: true }).click()
  await page.getByText('私有知识库', { exact: true }).click()
  await expect(page.getByTestId('knowledge-library')).toBeVisible()
  await expect(page.getByRole('button', { name: '计算机基础', exact: true })).toBeVisible()
  return mutations
}
async function snapshot(page: Page, id: string) {
  for (const width of [390, 320]) {
    await page.setViewportSize({ width, height: 812 })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await expect
      .poll(() =>
        page
          .locator('.phone-bottom .btn')
          .first()
          .evaluate((el) => getComputedStyle(el).backgroundColor),
      )
      .toBe('rgb(51, 106, 232)')
    await page.screenshot({ path: `${screenshots}/${id}-${width}.png` })
  }
  await page.setViewportSize({ width: 390, height: 812 })
}
test('K01–K03：原型书架、搜索、文件夹新增编辑和删除，资料保留', async ({ page }) => {
  const mutations = await setup(page)
  await snapshot(page, 'K01')
  await page.locator('input[placeholder="搜索文件夹或材料"]').fill('闭包')
  await expect(
    page.getByRole('button', { name: '查看资料：JavaScript 闭包笔记.pdf', exact: true }),
  ).toBeVisible()
  await page.locator('input[placeholder="搜索文件夹或材料"]').fill('')
  await page.getByRole('button', { name: '计算机基础', exact: true }).click()
  await snapshot(page, 'K02')
  await page.getByRole('button', { name: '编辑文件夹', exact: true }).click()
  await snapshot(page, 'K03')
  await page.locator('input').fill('网络知识')
  await page.getByRole('button', { name: '保存文件夹', exact: true }).click()
  await expect(page.getByText('网络知识', { exact: true })).toBeVisible()
  await page.reload()
  await page.getByText('我的', { exact: true }).click()
  await page.getByText('私有知识库', { exact: true }).click()
  await page.getByRole('button', { name: '网络知识', exact: true }).click()
  await page.getByRole('button', { name: '编辑文件夹', exact: true }).click()
  await page.getByRole('button', { name: '删除此文件夹', exact: true }).click()
  await page.getByText('删除', { exact: true }).click()
  await expect(page.getByRole('button', { name: '未分类资料', exact: true })).toBeVisible()
  expect(mutations.filter((x) => x.includes('/knowledge/documents'))).toEqual([])
  await page.getByRole('button', { name: /新建知识文件夹/ }).click()
  await page.locator('input').fill('本机新书架')
  await page.getByRole('button', { name: '保存文件夹', exact: true }).click()
  await expect(page.getByText('本机新书架', { exact: true })).toBeVisible()
})
test('K04–K05：导入切换、真实文件预览、资料引用与展开上下文', async ({ page }) => {
  await setup(page)
  await page.getByText('添加资料', { exact: true }).click()
  const chooser = page.waitForEvent('filechooser')
  await page.getByRole('button', { name: /选择文档/ }).click()
  await (
    await chooser
  ).setFiles({
    name: '网络基础课程.md',
    mimeType: 'text/markdown',
    buffer: Buffer.from('# HTTP\nHTTP 是无状态协议。'),
  })
  await snapshot(page, 'K04')
  await page.getByText('添加链接', { exact: true }).click()
  await expect(page.locator('input[placeholder="粘贴公开网页链接"]')).toBeVisible()
  await page.getByText('上传文档', { exact: true }).click()
  await expect(page.getByText('网络基础课程.md', { exact: true })).toBeVisible()
  await page.locator('.mini-back').click()
  await page.getByRole('button', { name: '查看资料：HTTP 学习笔记.pdf', exact: true }).click()
  await snapshot(page, 'K05')
  await page.getByRole('button', { name: /展开上下文/ }).click()
  await expect(page.locator('.knowledge-context')).toContainText('Cookie 在客户端携带会话标识')
  await expect(page.locator('.knowledge-context')).toContainText('第 3 页')
})
test('K06 与 L06：默认联网、一层多选主题、真实提交契约和原型确认页', async ({ page }) => {
  const mutations = await setup(page)
  await page.getByRole('button', { name: '根据资料出题', exact: true }).click()
  await expect(page.locator('taro-radio-core[value="network"]')).toHaveAttribute('checked')
  await snapshot(page, 'K06')
  await page.getByRole('button', { name: '生成知识库关卡', exact: true }).click()
  await expect(page.getByTestId('knowledge-confirm')).toBeVisible()
  await page.getByText('Cookie 与 Session 的区别', { exact: true }).click()
  await expect(page.locator('.knowledge-prototype-topic.selected')).toHaveCount(2)
  await snapshot(page, 'L06')
  expect(mutations).toContain('POST /api/v1/knowledge/quiz-preparations')
})
test('切换账号后不显示之前的本机书架和资料', async ({ page }) => {
  await setup(page)
  await page.evaluate(() =>
    localStorage.setItem(
      'levelup.auth.v1',
      JSON.stringify({ data: { token: 'prototype-b' }, expire: null }),
    ),
  )
  await page.reload()
  await expect(page.locator('textarea')).toBeVisible()
  await page.getByText('我的', { exact: true }).click()
  await page.getByText('私有知识库', { exact: true }).click()
  await expect(page.getByText('计算机基础', { exact: true })).toHaveCount(0)
  await expect(page.getByText('HTTP 学习笔记.pdf', { exact: true })).toHaveCount(0)
})
