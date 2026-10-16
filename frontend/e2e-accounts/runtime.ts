import { APIRequestContext, expect } from '@playwright/test'
export const apiOrigin = process.env.LEVELUP_E2E_API_ORIGIN || 'http://127.0.0.1:8001'
export async function confirmedSession(request: APIRequestContext, headers: Record<string, string>, count = 3) {
  const key = 'e2e-' + Date.now() + '-' + Math.random()
  const response = await request.post(apiOrigin + '/api/v1/quiz/preparations', { headers: { ...headers, 'Idempotency-Key': 'prepare-' + key }, data: { text: 'HTTP' } })
  expect(response.status()).toBe(200)
  const pid = (await response.json()).data.id
  let prepared: any
  await expect.poll(async () => { prepared = (await (await request.get(apiOrigin + '/api/v1/quiz/preparations/' + pid, { headers })).json()).data; return prepared.status }).toBe('ready')
  const candidate = prepared.content.candidates[0], focus = candidate.focuses[0]
  const submitted = await request.post(apiOrigin + '/api/v1/quiz/generate', { headers: { ...headers, 'Idempotency-Key': key }, data: { preparation_id: pid, scope_version: prepared.version, candidate_id: candidate.id, focus_id: focus.id, scope_point_ids: focus.points.map((p: any) => p.id), question_count: count, difficulty: 'easy' } })
  expect(submitted.status()).toBe(200)
  let operation: any
  await expect.poll(async () => { operation = (await (await request.get(apiOrigin + '/api/v1/operations/' + key, { headers })).json()).data; return operation.status }).toBe('succeeded')
  return operation.result
}
