import { fireEvent, render, screen, within } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import LocalResumeLab from './LocalResumeLab'
const start = () => { render(<LocalResumeLab />); fireEvent.change(screen.getByRole('textbox', { name: '简历原文' }), { target: { value: '项目经历\n我编写了Python脚本。\n\n团队负责，我计划学习部署。' } }); fireEvent.click(screen.getByRole('button', { name: '导入并核对原文' })) }
it('keeps actual role forms, typed notes and source independent on switches, without requests or storage', () => {
  const fetcher = vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('no network')); start()
  const a = (screen.getByLabelText('当前岗位') as HTMLSelectElement).value
  fireEvent.click(screen.getByLabelText('选用条目 1')); fireEvent.change(screen.getByLabelText('岗位草稿 1'), { target: { value: 'A的用户自述草稿' } })
  fireEvent.click(screen.getByRole('button', { name: '新增Python后端实习生草稿' })); const b = (screen.getByLabelText('当前岗位') as HTMLSelectElement).value
  expect(screen.getByLabelText('岗位草稿 1')).toHaveValue('我编写了Python脚本。'); expect(screen.getByLabelText('选用条目 1')).not.toBeChecked()
  fireEvent.change(screen.getByLabelText('简历版式'), { target: { value: 'minimal' } }); fireEvent.change(screen.getByLabelText('姓名'), { target: { value: '公开合成同学' } })
  fireEvent.change(screen.getByLabelText('当前岗位'), { target: { value: a } }); expect(screen.getByLabelText('岗位草稿 1')).toHaveValue('A的用户自述草稿'); expect(screen.getByLabelText('简历版式')).toHaveValue('classic'); expect(screen.getByLabelText('姓名')).toHaveValue('公开合成同学')
  fireEvent.change(screen.getByLabelText('当前岗位'), { target: { value: b } }); expect(screen.getByLabelText('简历版式')).toHaveValue('minimal')
  expect(screen.getByLabelText('完整简历原文')).toHaveTextContent('团队负责，我计划学习部署。'); expect(fetcher).not.toHaveBeenCalled(); fetcher.mockRestore(); expect(localStorage.length).toBe(0)
})
it('suggestions show exact source and JD basis, require explicit application and keep risky originals separate', () => {
  start(); fireEvent.click(screen.getByRole('button', { name: '新增Python后端实习生草稿' }))
  const suggestions = screen.getByRole('region', { name: '可解释岗位建议' }); expect(suggestions).toHaveTextContent('建议依据：')
  expect(screen.getByLabelText('选用条目 1')).not.toBeChecked(); fireEvent.click(within(suggestions).getByRole('button', { name: '选用原句并前移 · 1' }))
  expect(screen.getByLabelText('选用条目 1')).toBeChecked(); expect(screen.getByLabelText('岗位草稿 1')).toHaveValue('我编写了Python脚本。')
  expect(within(suggestions).getByRole('button', { name: '选用原句并前移 · 2' })).toBeDisabled()
  expect(screen.getByRole('article', { name: '用户自述简历草稿' })).not.toHaveTextContent('平台已认证')
})
it('profile markup is inert, credential values are refused and templates do not change source trust', () => {
  start(); fireEvent.change(screen.getByLabelText('姓名'), { target: { value: '<img src=x onerror=alert(1)>' } }); expect(document.querySelector('.resume-lab img')).toBeNull()
  fireEvent.change(screen.getByLabelText('联系信息'), { target: { value: 'Bearer syntheticsecret1234567890' } }); expect(screen.getByLabelText('联系信息')).toHaveValue('')
  expect(screen.getByRole('alert')).toHaveTextContent('岗位修改未通过来源、版本或状态校验，未应用。'); fireEvent.change(screen.getByLabelText('简历版式'), { target: { value: 'minimal' } }); expect(screen.getByRole('article', { name: '用户自述简历草稿' })).toHaveAttribute('data-template', 'minimal')
})
