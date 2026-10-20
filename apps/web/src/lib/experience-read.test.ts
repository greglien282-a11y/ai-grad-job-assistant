import { expect, it, vi } from 'vitest'
import fixtures from '../test/experience-read-fixtures.json'
import { createReadApi } from './experience-read'

const f = fixtures.summary.confirmed[0]
const a = { sessionId: f.session_id, projectId: f.project_id, token: 'synthetic-credential-'.repeat(3) }
it('uses only explicit GET v2 paths and headers, without operation keys or credentials in URLs', async () => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(fixtures.summary)).mockResolvedValueOnce(Response.json(f)).mockResolvedValueOnce(Response.json(fixtures.export))
  const api = createReadApi(fetcher)
  await api.summary(a); await api.fact(a, f.id); await api.export(a)
  expect(fetcher.mock.calls.map(c => c[0])).toEqual([
    `/api/v2/experience/projects/${a.projectId}/experience-summary`, `/api/v2/experience/sessions/${a.sessionId}/facts/${f.id}`, `/api/v2/experience/sessions/${a.sessionId}/export`,
  ])
  for (const [url, options] of fetcher.mock.calls) {
    expect(String(url)).not.toContain(a.token); expect(options?.method).toBe('GET'); expect(options?.body).toBeUndefined()
    expect(options?.headers).toEqual({ Authorization: `Bearer ${a.token}`, Accept: 'application/json' }); expect(options?.redirect).toBe('error')
  }
})
it.each([[401, 'auth'], [404, 'missing'], [409, 'conflict'], [503, 'unavailable']] as const)('safely maps HTTP %i with no fallback', async (status, kind) => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValue(Response.json({ error: { code: 'private ' + a.token, message: 'private statement' } }, { status }))
  await expect(createReadApi(fetcher).summary(a)).rejects.toMatchObject({ kind })
  expect(fetcher).toHaveBeenCalledTimes(1)
})
it('identifies default closed separately and never falls back', async () => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValue(Response.json({ error: { code: 'experience_read_disabled' } }, { status: 503 }))
  await expect(createReadApi(fetcher).summary(a)).rejects.toMatchObject({ kind: 'disabled' }); expect(fetcher).toHaveBeenCalledTimes(1)
})
it('does not propagate network diagnostics or retry', async () => {
  const fetcher = vi.fn<typeof fetch>().mockRejectedValue(new Error(a.token + ' private audit'))
  await expect(createReadApi(fetcher).summary(a)).rejects.toMatchObject({ kind: 'network', message: '网络连接中断，请检查连接后手动读取。' })
  expect(fetcher).toHaveBeenCalledTimes(1)
})
it.each(['version', 'corrupt', 'identity'])('rejects %s on the real consumer path', async fault => {
  const value = structuredClone(fixtures.summary)
  if (fault === 'version') Object.assign(value, { summary_contract_version: 99 })
  if (fault === 'corrupt') Object.assign(value.confirmed[0], { classification_citations: [{}] })
  if (fault === 'identity') value.confirmed[0].session_id = '00000000-0000-4000-8000-000000000001'
  const fetcher = vi.fn<typeof fetch>().mockResolvedValue(Response.json(value))
  await expect(createReadApi(fetcher).summary(a)).rejects.toMatchObject({ kind: fault === 'version' ? 'version' : 'contract' })
})
it('refuses invalid identifiers before issuing HTTP', async () => {
  const fetcher = vi.fn<typeof fetch>()
  await expect(createReadApi(fetcher).fact(a, '../private')).rejects.toMatchObject({ kind: 'input' })
  expect(fetcher).not.toHaveBeenCalled()
})
it('distinguishes an interrupted successful response body from invalid JSON without disclosing diagnostics', async () => {
  const broken = new Response(new ReadableStream({ start(c) { c.error(new Error(a.token)) } }))
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(broken).mockResolvedValueOnce(new Response('{invalid'))
  await expect(createReadApi(fetcher).summary(a)).rejects.toMatchObject({ kind: 'network' })
  await expect(createReadApi(fetcher).summary(a)).rejects.toMatchObject({ kind: 'contract' })
})
