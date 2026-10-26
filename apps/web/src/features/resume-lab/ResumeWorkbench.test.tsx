import { fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { expect, it, vi } from 'vitest'
import LocalResumeLab from './LocalResumeLab'
import ResumeWorkbench from './ResumeWorkbench'
import type { Workbench } from './import'

it('lets a graduate import, inspect and manually structure source without a Fact or request', () => {
  const fetcher = vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('must not call'))
  render(<LocalResumeLab />)
  fireEvent.change(screen.getByLabelText('简历原文'), { target: { value: '项目经历\n我没有部署服务。' } })
  fireEvent.click(screen.getByRole('button', { name: '导入并核对原文' }))
  expect(screen.getByLabelText('完整简历原文')).toHaveTextContent('我没有部署服务。')
  fireEvent.change(screen.getByLabelText('段落标题 1'), { target: { value: '个人边界' } })
  fireEvent.click(screen.getByRole('button', { name: '应用段落 1' }))
  expect(screen.getByLabelText('段落标题 1')).toHaveValue('个人边界')
  fireEvent.change(screen.getByLabelText('手工声明'), { target: { value: '团队负责，我未参与部署。' } })
  fireEvent.click(screen.getByRole('button', { name: '添加未审核声明' }))
  expect(screen.getByText('团队负责，我未参与部署。')).toBeVisible()
  expect(fetcher).not.toHaveBeenCalled(); fetcher.mockRestore()
  expect(sessionStorage.length).toBe(0); expect(localStorage.length).toBe(0)
  fireEvent.change(screen.getByLabelText('简历原文'), { target: { value: '新材料' } })
  expect(screen.queryByLabelText('完整简历原文')).toBeNull()
})
it('invalid references leave the current source unchanged and show a safe error', () => {
  render(<LocalResumeLab />); fireEvent.click(screen.getByRole('button', { name: '填入公开合成简历' })); fireEvent.click(screen.getByRole('button', { name: '导入并核对原文' }))
  const original = screen.getByLabelText('完整简历原文').textContent
  fireEvent.change(screen.getByLabelText('终点 1'), { target: { value: '90000' } }); fireEvent.click(screen.getByRole('button', { name: '应用段落 1' }))
  expect(screen.getByRole('alert')).toHaveTextContent('引用校验失败'); expect(screen.getByLabelText('完整简历原文').textContent).toBe(original)
})
it('a slow file cannot replace newer pasted input', async () => {
  let release!: (b: ArrayBuffer) => void
  const slow = { name: 'slow.txt', size: 20, arrayBuffer: () => new Promise<ArrayBuffer>(resolve => { release = resolve }) }
  function Host() { const [w, set] = useState<Workbench | null>(null); return <ResumeWorkbench value={w} onChange={set} /> }
  render(<Host />)
  fireEvent.change(screen.getByLabelText('选择本地文本文件'), { target: { files: [slow] } })
  fireEvent.change(screen.getByLabelText('简历原文'), { target: { value: '新的本地文字。' } }); fireEvent.click(screen.getByRole('button', { name: '导入并核对原文' }))
  release(new TextEncoder().encode('过时的文件文字。').buffer); await Promise.resolve()
  expect(screen.getByLabelText('完整简历原文')).toHaveTextContent('新的本地文字。')
})
