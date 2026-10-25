import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import { basisLabel, parse, parseJson } from './contract'

const cases = JSON.parse(readFileSync(new URL('../corpus.json', import.meta.url), 'utf8')) as
  { name: string; json: string; status: string; code?: string }[]
describe('shared Python/TypeScript corpus', () => {
  for (const c of cases) it(c.name, () => {
    const result = parseJson(c.json)
    expect(result.status).toBe(c.status)
    if (c.code) expect(result.code).toBe(c.code)
    expect(result).toMatchObject({ truth_verified: false, persistence_authorized: false,
      authentication_verified: false, database_history_verified: false, language_validation_replayed: false })
    if (c.status === 'rejected') expect(result.view).toBeNull()
  })
})
it('does not mutate input and copies the result', () => {
  const input = JSON.parse(cases[0].json)
  const before = JSON.stringify(input)
  const result = parse(input)
  expect(JSON.stringify(input)).toBe(before)
  if (!result.view) throw new Error('fixture not parsed')
  result.view.subject.statement = 'changed output'
  expect(JSON.stringify(input)).toBe(before)
})
it('labels declarations and missing evidence honestly', () => {
  const labels = cases.filter(c => c.status === 'parsed_candidate').map(c => {
    const result = parseJson(c.json)
    if (!result.view) throw new Error('fixture not parsed')
    return basisLabel(result.view)
  })
  expect(labels).toContain('暂无分类依据记录')
  expect(labels).toContain('旧资料未分类，未推断完成情况')
  expect(labels).toContain('用户已声明分类；不代表平台独立认证')
})
it('rejects non-JSON and caller-supplied truth authority', () => {
  for (const value of [null, undefined, 5, [], 'null', '{broken']) expect(parseJson(value).status).toBe('rejected')
  const data = JSON.parse(cases[0].json)
  data.truth_verified = true
  expect(parse(data).view).toBeNull()
})
it('has no browser or network dependency', () => {
  const source = readFileSync(new URL('./contract.ts', import.meta.url), 'utf8')
  expect(source).not.toMatch(/\b(fetch|XMLHttpRequest|localStorage|sessionStorage|document|window)\b/)
})
