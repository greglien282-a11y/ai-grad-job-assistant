import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import fixtures from '../../test/experience-read-fixtures.json'
import TypedRead from './TypedRead'

afterEach(() => vi.unstubAllGlobals())
const f = fixtures.summary.confirmed[0]
function fill() {
  fireEvent.change(screen.getByLabelText('会话 ID'), { target: { value: f.session_id } })
  fireEvent.change(screen.getByLabelText('项目 ID'), { target: { value: f.project_id } })
  fireEvent.change(screen.getByLabelText('会话凭证'), { target: { value: 'synthetic-token-'.repeat(4) } })
}
it('waits for explicit read and consumes summary and standalone fact without fetching export', async () => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(fixtures.summary)).mockResolvedValueOnce(Response.json(f))
  vi.stubGlobal('fetch', fetcher)
  render(<TypedRead />); fill(); expect(fetcher).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: '读取新版资料' }))
  await screen.findByText('summary v2 · revision ' + fixtures.summary.context_revision)
  expect(screen.getByText('用户确认和用户提供材料支持均不代表平台独立认证。此页不提供审核、编辑或模型提交。', { exact: false })).toBeVisible()
  expect(screen.getAllByText('计划不属于已完成成果').length).toBeGreaterThan(0)
  expect(fetcher).toHaveBeenCalledTimes(1)
  fireEvent.click(screen.getByRole('button', { name: '查看来源 ' + f.id }))
  const detail = await screen.findByRole('region', { name: '事实来源详情' })
  expect(within(detail).getByText('暂无分类依据记录')).toBeVisible(); expect(fetcher).toHaveBeenCalledTimes(2)
  expect(sessionStorage.length).toBe(0); expect(window.location.search).toBe('')
})
it('clears old content on failure and on credential changes', async () => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(fixtures.summary)).mockResolvedValueOnce(Response.json({ error: { code: 'experience_read_disabled' } }, { status: 503 }))
  vi.stubGlobal('fetch', fetcher); render(<TypedRead />); fill()
  fireEvent.click(screen.getByRole('button', { name: '读取新版资料' })); await screen.findByText('summary v2 · revision ' + fixtures.summary.context_revision)
  fireEvent.click(screen.getByRole('button', { name: '查看来源 ' + f.id })); expect(await screen.findByRole('alert')).toHaveTextContent('新版读取暂不可用')
  expect(screen.queryByText('summary v2 · revision ' + fixtures.summary.context_revision)).not.toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('会话凭证'), { target: { value: 'changed' } }); expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})
it('ignores a late response after credentials change', async () => {
  let resolve!: (value: Response) => void
  const fetcher = vi.fn<typeof fetch>().mockImplementation(() => new Promise(r => { resolve = r }))
  vi.stubGlobal('fetch', fetcher); render(<TypedRead />); fill()
  fireEvent.click(screen.getByRole('button', { name: '读取新版资料' }))
  fireEvent.change(screen.getByLabelText('会话凭证'), { target: { value: 'changed' } })
  resolve(Response.json(fixtures.summary)); await waitFor(() => expect(screen.queryByText('summary v2 · revision ' + fixtures.summary.context_revision)).not.toBeInTheDocument())
})
