import { expect, it } from 'vitest'
import { analyzeJD, keywords } from './jd'
it('keeps exact code-point spans through emoji, decomposed accents, ZWJ, CRLF and punctuation', () => {
  const raw = '🧪👩‍💻é工程师\r\n必须掌握Python；Docker优先。\n本科相关专业。3.5年经验！'
  const job = analyzeJD(raw)
  expect(job.requirements.length).toBe(5)
  for (const r of job.requirements) expect(Array.from(raw).slice(r.start, r.end).join('')).toBe(r.quote)
  expect(job.requirements.find(r => r.quote.includes('Python'))).toMatchObject({ category: 'technical', priority: 'must' })
  expect(job.requirements.find(r => r.quote.includes('Docker'))).toMatchObject({ priority: 'bonus' })
  expect(job.requirements.find(r => r.quote.includes('本科'))).toMatchObject({ category: 'education' })
  expect(job.requirements.at(-1)).toMatchObject({ category: 'experience' })
})
it('fails empty JD without inventing a job', () => expect(() => analyzeJD(' \r\n')).toThrow('请先'))
it('rejects null characters and oversized input', () => { expect(() => analyzeJD('x\0')).toThrow(); expect(() => analyzeJD('x'.repeat(12001))).toThrow() })
it('does not split English skill names or confuse JavaScript with Java', () => { expect(keywords('JavaScript')).toEqual(['javascript']); expect(analyzeJD('Python developer\nSQL required.').requirements).toHaveLength(2) })
it('flags contradictory requirements and non-required/unknown lines for manual judgment', () => {
  const r = analyzeJD('必须掌握Python。无需Python经验。善于思考。Docker必须且优先。').requirements
  expect(r.map(x => x.priority)).toEqual(['uncertain', 'uncertain', 'uncertain', 'uncertain'])
  expect(r[0].conflict).toBe(true)
})
