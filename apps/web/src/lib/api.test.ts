import { describe, expect, it, vi } from 'vitest'
import { getHealth } from './api'

describe('GET /api/v1/health client', () => {
  it('accepts an ok response', async () => {
    const fetcher = vi.fn(async () => new Response(JSON.stringify({ status: 'ok' }), { status: 200 }))
    await expect(getHealth(fetcher as typeof fetch)).resolves.toEqual({ status: 'ok' })
    expect(fetcher).toHaveBeenCalledOnce()
  })

  it('rejects an unexpected API payload', async () => {
    const fetcher = vi.fn(async () => new Response(JSON.stringify({ status: 'unknown' }), { status: 200 }))
    await expect(getHealth(fetcher as typeof fetch)).rejects.toThrow('health schema')
  })

  it('handles server errors', async () => {
    const fetcher = vi.fn(async () => new Response('unavailable', { status: 503 }))
    await expect(getHealth(fetcher as typeof fetch)).rejects.toThrow('HTTP 503')
  })
})
