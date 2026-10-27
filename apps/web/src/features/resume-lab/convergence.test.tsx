import { fireEvent, render, screen, within } from '@testing-library/react'
import { expect, it } from 'vitest'
import LocalResumeLab from './LocalResumeLab'
import { sourceTransition } from './source-transition'
import { addManual, importText, type Workbench } from './import'
import { admission, newDraft, printable, setJob, validate } from './draft'
import { applySourceSuggestions, suggestions } from './workspace'

const raw = '项目经历\n👩‍💻 我编写了Python脚本。\n\n技能\nPython课程基础。\n\n团队负责，我计划学习部署。'
const click = (name: string) => fireEvent.click(screen.getByRole('button', { name }))
const change = (name: string, value: string) => fireEvent.change(screen.getByLabelText(name), { target: { value } })
function start() { render(<LocalResumeLab />); change('简历原文', raw); click('导入并核对原文'); click('新增Python后端实习生草稿'); fireEvent.click(screen.getByLabelText('选用条目 1')); click('开始岗位三题'); change('我的复习回答', '课程练习，不是部署。') }

it('preserves both role drafts, ordering and answers for citation-identical metadata and safe undo', () => {
  start(); const role = (screen.getByLabelText('当前岗位') as HTMLSelectElement).value
  change('段落标题 1', '课程脚本'); change('段落类型 1', 'skill'); click('应用段落 1'); click('下移段落 1')
  expect(screen.getByLabelText('我的复习回答')).toHaveValue('课程练习，不是部署。')
  expect(screen.getByLabelText('当前岗位')).toHaveValue(role)
  expect((screen.getByLabelText('当前岗位') as HTMLSelectElement).options).toHaveLength(2)
  expect(screen.getByLabelText('岗位草稿 1')).toHaveValue('👩‍💻 我编写了Python脚本。')
  expect(screen.getByLabelText('选用条目 1')).toBeChecked()
  click('撤销上一步（拒绝记录保留）')
  expect(screen.getByLabelText('段落标题 2')).toHaveValue('课程脚本')
})

it('requires confirmation for changed ranges and allows cancellation without losing roles or answers', () => {
  start(); change('起点 1', '7'); click('应用段落 1')
  expect(screen.getByRole('alertdialog')).toHaveTextContent('引用身份、区间或原句改变')
  expect(screen.queryByLabelText('岗位草稿 1')).toBeNull()
  expect(screen.getByRole('button', { name: '下载本地草稿 JSON' })).toBeDisabled()
  click('取消变更，保留原岗位'); expect(screen.getByLabelText('我的复习回答')).toHaveValue('课程练习，不是部署。')
  change('起点 1', '7'); click('应用段落 1'); click('确认更换来源并重置岗位')
  expect((screen.getByLabelText('当前岗位') as HTMLSelectElement).options).toHaveLength(1)
  expect(screen.queryByLabelText('我的复习回答')).toBeNull(); expect(screen.getByLabelText('选用条目 1')).not.toBeChecked()
})

it('appearance and view switches preserve answers; source edits and JD changes invalidate them', () => {
  start(); change('排版密度', 'compact'); change('简历版式', 'minimal'); change('分页目标', 'multiple')
  click('来源审查'); expect(screen.getByRole('region', { name: '来源审查详情' })).toHaveTextContent('导入原文')
  expect(screen.getByLabelText('我的复习回答')).toHaveValue('课程练习，不是部署。')
  click('简历输出'); expect(screen.getByLabelText('我的复习回答')).toHaveValue('课程练习，不是部署。')
  change('岗位草稿 1', '用户自己的课程说明。'); expect(screen.queryByLabelText('我的复习回答')).toBeNull()
  click('开始岗位三题'); change('我的复习回答', '新回答'); change('目标岗位原文', '新岗位\nPython基础。')
  expect(screen.queryByLabelText('我的复习回答')).toBeNull()
})

it('keeps edited risky and rejected text out of output on every view switch', () => {
  start(); fireEvent.click(screen.getByLabelText('选用条目 3')); change('岗位草稿 3', '我独立部署了服务。')
  click('拒绝本地条目 1')
  for (const view of ['来源审查', '简历输出', '来源审查', '简历输出']) {
    click(view)
    const paper = document.querySelector('.local-resume-paper')!
    expect(paper).not.toHaveTextContent('我独立部署了服务。'); expect(paper).not.toHaveTextContent('👩‍💻 我编写了Python脚本。')
    expect(paper).not.toHaveTextContent('JD原句'); expect(paper).not.toHaveTextContent('G4')
  }
  click('来源审查'); const audit = screen.getByRole('region', { name: '来源审查详情' })
  expect(audit).toHaveTextContent('我独立部署了服务。'); expect(audit).toHaveTextContent('本地拒绝记录保留')
})

it('requires full snapshot and citation identities, rejects malformed proposals and never mutates inputs', () => {
  const w = importText(raw), before = JSON.stringify(w)
  const metadata = { ...w, excerpts: w.excerpts.map(e => ({ ...e, label: '新标题', section: 'other' as const })).reverse() }
  expect(sourceTransition(w, metadata).preserve).toBe(true)
  for (const edit of [
    { ...w, source: { ...w.source, id: crypto.randomUUID() }, excerpts: [] },
    { ...w, source: { ...w.source, text: w.source.text + '补充原文。' } },
    { ...w, excerpts: w.excerpts.map((e, i) => i ? e : { ...e, id: crypto.randomUUID() }) },
    addManual(w, '用户说明。'),
  ]) expect(sourceTransition(w, edit as Workbench).preserve).toBe(false)
  expect(() => sourceTransition(w, { ...w, excerpts: [{ ...w.excerpts[0], quote: '伪造' }] })).toThrow()
  expect(JSON.stringify(w)).toBe(before)
})

it('shows matched JD words and explicit gap independently of source trust; batch only uses eligible exact originals', () => {
  let d = setJob(newDraft(addManual(importText(raw), '我有Python课程基础。')), '后端实习\n必备：Python基础。\n加分：部署经验。')
  let list = suggestions(d); expect(list[0].eligible).toBe(true)
  expect(list[0].links[0].words).toContain('python'); expect(list[0].links[0].requirement.quote).toContain('Python')
  const applied = applySourceSuggestions(d)
  expect(printable(applied).every(e => e.text === e.original && admission(applied, e).kind === 'draft')).toBe(true)
  expect(printable(applied).some(e => e.source_kind === 'user_manual_statement')).toBe(true)
  d = validate({ ...d, assessments: d.assessments.map(a => ({ ...a, state: 'gap' })) })
  list = suggestions(d); expect(list.every(s => !s.eligible)).toBe(true); expect(list.some(s => s.status === 'gap')).toBe(true)
  expect(printable(applySourceSuggestions(d))).toHaveLength(0)
  render(<LocalResumeLab />); change('简历原文', raw); click('导入并核对原文'); click('新增Python后端实习生草稿')
  const panel = screen.getByRole('region', { name: '可解释岗位建议' })
  expect(panel).toHaveTextContent('匹配词：python'); expect(panel).toHaveTextContent('需要补充证据')
  expect(within(panel).getByRole('button', { name: /选用全部可解释原句/ })).toBeEnabled()
})
