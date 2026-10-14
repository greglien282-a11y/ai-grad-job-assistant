import { describe, expect, it, vi } from 'vitest'
import fixtures from '../test/mining-fixtures.json'
import { createExperienceApi } from './experience'
import { createMiningApi } from './mining'
const c = { sessionId: fixtures.created.session_id, token: fixtures.created.access_token }
describe('mining response safety contracts', () => {
  it('rejects unconfirmed statements and new prose in a readable summary', async () => {
    for (const payload of [{ ...fixtures.initialSummary, text: 'Invented performance gain' }, { ...fixtures.initialSummary, confirmed: fixtures.initial.facts, text: fixtures.initial.facts.map(f => f.statement).join('\n') }]) {
      const fetcher = vi.fn(async () => new Response(JSON.stringify(payload), { status: 200 }))
      await expect(createMiningApi(createExperienceApi(fetcher as typeof fetch)).summary(c, fixtures.created.project_id)).rejects.toThrow('格式异常')
    }
  })
  it('rejects a response claiming a real provider in synthetic mode', async () => {
    const fetcher = vi.fn(async () => new Response(JSON.stringify({ ...fixtures.initialRun, synthetic: false, provider: 'unapproved' }), { status: 200 }))
    await expect(createMiningApi(createExperienceApi(fetcher as typeof fetch)).recover(c, 'synthetic-key')).rejects.toThrow('格式异常')
    expect(fetcher).toHaveBeenCalledOnce()
    const [, init] = fetcher.mock.calls[0] as unknown as [string, RequestInit]
    expect(init.method).toBe('GET')
  })
})
