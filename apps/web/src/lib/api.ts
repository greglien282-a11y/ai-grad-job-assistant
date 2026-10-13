export type HealthResponse = { status: 'ok' }

/** This module intentionally exposes only the M1-0 health contract. */
export async function getHealth(fetcher: typeof fetch = fetch): Promise<HealthResponse> {
  const baseUrl = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')
  const response = await fetcher(`${baseUrl}/api/v1/health`, {
    headers: { Accept: 'application/json' },
  })
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`)
  }
  const payload: unknown = await response.json()
  if (
    typeof payload !== 'object' ||
    payload === null ||
    !('status' in payload) ||
    payload.status !== 'ok'
  ) {
    throw new Error('API response does not match health schema')
  }
  return { status: 'ok' }
}
