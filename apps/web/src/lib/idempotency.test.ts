import { afterEach, expect, it, vi } from 'vitest'
import vector from '../../../shared/idempotency-vector.json'
import { bodyTag, hmac, newPending } from './idempotency'
import { createExperienceApi } from './experience'

afterEach(() => vi.restoreAllMocks())
it('matches the shared Python HMAC proof and UTF-8 request tag', async () => {
  const bytes = await hmac(vector.token, `pathwise-idempotency-v1\n${vector.kind}\n${vector.scope}\n${vector.issued}\n${vector.nonce}`)
  const proof = btoa(String.fromCharCode(...bytes)).replaceAll('+','-').replaceAll('/','_').replaceAll('=','')
  expect(`v1.${vector.issued}.${vector.nonce}.${proof}`).toBe(vector.key)
  expect(await bodyTag(vector.token,vector.kind,vector.scope,vector.body)).toBe(vector.bodyTag)
})
it('honors Retry-After without automatic or early network retries', async () => {
  let now = Date.now(); vi.spyOn(Date,'now').mockImplementation(() => now)
  const p = await newPending('Synthetic')
  const fetcher = vi.fn(async () => new Response(JSON.stringify({error:{code:'rate_limited'}}),{status:429,headers:{'Retry-After':'10'}}))
  const api = createExperienceApi(fetcher)
  await expect(api.create('Synthetic',p)).rejects.toMatchObject({status:429})
  await expect(api.create('Synthetic',p)).rejects.toMatchObject({status:429})
  expect(fetcher).toHaveBeenCalledTimes(1)
  now += 10001
  await expect(api.create('Synthetic',p)).rejects.toMatchObject({status:429})
  expect(fetcher).toHaveBeenCalledTimes(2)
})
