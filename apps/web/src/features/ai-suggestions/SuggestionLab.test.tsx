import { fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import LocalResumeLab from '../resume-lab/LocalResumeLab'
const raw = '项目经历\n我编写了Python脚本。\n\n团队负责，我计划学习部署。'
const click = (name: string) => fireEvent.click(screen.getByRole('button', { name }))
function start(enabled = true) {
  vi.stubEnv('VITE_PATHWISE_AI_SUGGESTIONS', enabled ? 'offline-v1' : '')
  render(<LocalResumeLab />)
  fireEvent.change(screen.getByLabelText('简历原文'), { target: { value: raw } }); click('导入并核对原文'); click('新增Python后端实习生草稿')
}
afterEach(() => vi.unstubAllEnvs())
it('is absent by default even while the original resume lab is operational', () => {
  start(false); expect(screen.queryByRole('region', { name: '离线AI建议审核实验室' })).toBeNull()
  expect(screen.getByLabelText('岗位草稿 1')).toHaveValue('我编写了Python脚本。')
})
it('shows original to JD to candidate and requires explicit exact-source acceptance with zero requests', () => {
  const fetcher = vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('forbidden')); start()
  click('生成离线Mock候选'); const panel = screen.getByRole('region', { name: '离线AI建议审核实验室' })
  expect(panel).toHaveTextContent('offline_mock'); expect(panel).toHaveTextContent('必备：Python基础与测试意识。')
  expect(screen.getByLabelText('选用条目 1')).not.toBeChecked(); click('接受原句顺序 · mock:1')
  expect(screen.getByLabelText('选用条目 1')).toBeChecked(); expect(screen.getByRole('article', { name: '用户自述简历草稿' })).toHaveTextContent('我编写了Python脚本。')
  expect(fetcher).not.toHaveBeenCalled(); fetcher.mockRestore(); expect(localStorage.length).toBe(0)
})
it('quarantines unsupported rewrites, preserves rejection on regeneration and never prints edited candidate text', () => {
  start(); click('查看公开合成风险反例')
  const panel = screen.getByRole('region', { name: '离线AI建议审核实验室' })
  expect(panel).toHaveTextContent('需要人工澄清'); expect(within(panel).getByRole('button', { name: '接受原句顺序 · risk:unsupported' })).toBeDisabled()
  fireEvent.change(screen.getByLabelText('待核对候选文字 · risk:unsupported'), { target: { value: '<img onerror=alert(1)> 用户补充，需要证据。' } })
  click('保留编辑到待核对区 · risk:unsupported'); expect(panel).toHaveTextContent('用户编辑待核对，未应用')
  expect(document.querySelector('.local-resume-paper')).not.toHaveTextContent('30%'); expect(document.querySelector('.local-resume-paper')).not.toHaveTextContent('用户补充')
  expect(panel.querySelector('img')).toBeNull(); click('拒绝候选 · risk:unsupported'); click('查看公开合成风险反例')
  expect(panel).toHaveTextContent('已拒绝（重新生成同一候选不解除）')
})
it('clears stale candidates on source or job edit and refuses unknown JSON without fallback', () => {
  start(); click('生成离线Mock候选'); fireEvent.change(screen.getByLabelText('岗位草稿 1'), { target: { value: '用户修改说明。' } })
  const panel = screen.getByRole('region', { name: '离线AI建议审核实验室' }); expect(panel).toHaveTextContent('旧候选已失效')
  fireEvent.change(screen.getByLabelText('候选 JSON'), { target: { value: '{"contract":"future-v9"}' } }); click('严格载入候选')
  expect(within(panel).getByRole('alert')).toHaveTextContent('候选未载入'); expect(within(panel).queryByRole('article')).toBeNull()
})

it('invalidates prior reasons when a user adjusts a JD requirement without changing its original quote', () => {
  start(); click('生成离线Mock候选')
  const panel = screen.getByRole('region', { name: '离线AI建议审核实验室' })
  expect(within(panel).getAllByRole('article').length).toBeGreaterThan(0)
  const original = screen.getAllByLabelText(/^条件描述 /)[0]
  fireEvent.change(original, { target: { value: '人工调整为需核对的其他条件。' } })
  expect(panel).toHaveTextContent('旧候选已失效'); expect(within(panel).queryByRole('article')).toBeNull()
})
