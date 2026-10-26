export type Priority = 'must' | 'bonus' | 'uncertain'
export type Category = 'technical' | 'education' | 'experience' | 'other'
export type Requirement = { id: string; text: string; quote: string; start: number; end: number; category: Category; priority: Priority; adjusted: boolean; conflict: boolean }
export type Job = { title: string; raw: string; requirements: Requirement[] }
const terms: [string, RegExp][] = [
  ['python', /\bpython\b/i], ['java', /\bjava\b/i], ['javascript', /\bjavascript\b/i], ['react', /\breact\b/i],
  ['sql', /\bsql\b/i], ['docker', /\bdocker\b/i], ['测试', /测试|\btest(?:ing)?\b/i],
  ['部署', /部署|\bdeploy(?:ment)?\b/i], ['脚本', /脚本|\bscript(?:ing)?\b/i], ['清洗', /清洗/],
]
export const keywords = (text: string) => terms.filter(([, pattern]) => pattern.test(text)).map(([term]) => term)
export function analyzeJD(raw: string): Job {
  if (!raw.trim()) throw new Error('请先粘贴岗位描述。')
  if (Array.from(raw).length > 12000 || /\0|[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/u.test(raw)) throw new Error('岗位描述过长或含无效字符。')
  const points = Array.from(raw), requirements: Requirement[] = []
  let begin = 0
  const add = (until: number) => {
    let start = begin, end = until
    while (start < end && /\s/.test(points[start])) start++
    while (end > start && /\s/.test(points[end - 1])) end--
    if (end <= start) return
    const quote = points.slice(start, end).join(''), keys = keywords(quote)
    const category: Category = /学历|本科|硕士|专业|degree|bachelor/i.test(quote) ? 'education' : /经验|年|实习经历|experience/i.test(quote) ? 'experience' : keys.length ? 'technical' : 'other'
    const must = /必须|必备|熟练|掌握|\bmust\b|\brequired\b/i.test(quote), bonus = /优先|加分|\bpreferred\b|\bbonus\b/i.test(quote)
    const negated = /无需|不要求|不必|非必须|not required/i.test(quote)
    requirements.push({ id: `jd-${start}-${end}`, text: quote, quote, start, end, category,
      priority: negated || must === bonus ? 'uncertain' : must ? 'must' : 'bonus', adjusted: false, conflict: must && bonus })
  }
  for (let i = 0; i < points.length; i++) {
    if (/[。！？!?\n；;]/.test(points[i]) || (points[i] === '.' && !/[0-9]/.test(points[i - 1] ?? ''))) { add(i + 1); begin = i + 1 }
  }
  add(points.length)
  // Opposing statements about the same finite literal skill need human review.
  for (const r of requirements) for (const other of requirements) {
    if (r === other || !keywords(r.text).some(k => keywords(other.text).includes(k))) continue
    if (/无需|不要求|不必|not required/i.test(r.text) !== /无需|不要求|不必|not required/i.test(other.text)) {
      r.conflict = other.conflict = true; r.priority = other.priority = 'uncertain'
    }
  }
  return { title: raw.split(/\r?\n/).find(line => line.trim())?.trim().slice(0, 80) ?? '目标岗位（请核对）', raw, requirements }
}
