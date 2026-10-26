import { fireEvent, render, screen, within } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import LocalResumeLab from './LocalResumeLab'

function start(raw = '项目经历\n我编写了图像读取脚本。\n\n技能\nPython课程基础。') {
  render(<LocalResumeLab />); fireEvent.change(screen.getByRole('textbox', { name: '简历原文' }), { target: { value: raw } }); fireEvent.click(screen.getByRole('button', { name: '导入并核对原文' }))
  fireEvent.click(screen.getByRole('button', { name: '填入视觉算法实习 JD' })); fireEvent.click(screen.getByRole('button', { name: '分析本地岗位' }))
}
it('makes a user-authored draft printable with original comparison, ordering, undo and three source-linked questions', () => {
  start(); fireEvent.click(screen.getByLabelText('选用条目 1')); fireEvent.click(screen.getByLabelText('选用条目 2'))
  fireEvent.change(screen.getByLabelText('岗位草稿 1'), { target: { value: '我自己补写的说明。' } })
  const paper = screen.getByRole('article', { name: '用户自述简历草稿' }); expect(within(paper).getByText('我自己补写的说明。')).toBeVisible(); expect(paper).toHaveTextContent('用户改写；原文：我编写了图像读取脚本。')
  fireEvent.click(screen.getByRole('button', { name: '撤销上一步（拒绝记录保留）' })); expect(screen.getByLabelText('岗位草稿 1')).toHaveValue('我编写了图像读取脚本。')
  fireEvent.click(screen.getByRole('button', { name: '上移条目 2' })); expect(paper.querySelector('.paper-entry')?.textContent).toContain('Python课程基础')
  const print = vi.spyOn(window, 'print').mockImplementation(() => undefined); fireEvent.click(screen.getByRole('button', { name: '打印用户草稿 / 保存 PDF' })); expect(print).toHaveBeenCalledOnce(); print.mockRestore()
  fireEvent.click(screen.getByRole('button', { name: '开始岗位三题' })); expect(screen.getByText('第 1 / 3 题')).toBeVisible(); expect(screen.getByText('当前草稿：Python课程基础。')).toBeVisible()
  fireEvent.change(screen.getByLabelText('我的复习回答'), { target: { value: '我没有指标，需要核对。' } }); fireEvent.click(screen.getByRole('button', { name: '下一道岗位问题' })); fireEvent.click(screen.getByRole('button', { name: '跳过岗位问题' })); fireEvent.click(screen.getByRole('button', { name: '完成岗位复习' }))
  expect(screen.getByText('三题复盘 · 不猜经历、不打分')).toBeVisible()
})
it('keeps rejected text blocked after undo and reimport with another source identity', () => {
  start('我编写了脚本。'); fireEvent.click(screen.getByLabelText('选用条目 1')); fireEvent.click(screen.getByRole('button', { name: '拒绝本地条目 1' }))
  fireEvent.click(screen.getByRole('button', { name: '撤销上一步（拒绝记录保留）' })); expect(screen.getByRole('button', { name: '打印用户草稿 / 保存 PDF' })).toBeDisabled()
  fireEvent.change(screen.getByRole('textbox', { name: '简历原文' }), { target: { value: '项目经历\n我编写了脚本。' } }); fireEvent.click(screen.getByRole('button', { name: '导入并核对原文' }))
  expect(screen.getByLabelText('选用条目 1')).toBeDisabled()
})
it('keeps team and planned source visible as context, and blocks removing its boundaries by editing', () => {
  start('我计划部署服务，团队负责。'); fireEvent.click(screen.getByLabelText('选用条目 1'))
  const paper = screen.getByRole('article', { name: '用户自述简历草稿' }); expect(paper).toHaveTextContent('背景、计划与限制 · 不是已完成个人贡献')
  fireEvent.change(screen.getByLabelText('岗位草稿 1'), { target: { value: '我独立部署了服务。' } }); expect(paper).not.toHaveTextContent('我独立部署了服务。'); expect(screen.getByRole('button', { name: '打印用户草稿 / 保存 PDF' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: '恢复原文 1' })); expect(paper).toHaveTextContent('我计划部署服务，团队负责。')
})
it('invalid restoration clears stale paper and never performs a network request', async () => {
  start(); fireEvent.click(screen.getByLabelText('选用条目 1'))
  const fetcher = vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('not allowed'))
  const file = { name: 'bad.json', size: 20, arrayBuffer: async () => new TextEncoder().encode('{"contract":"future"}').buffer }
  fireEvent.change(screen.getByLabelText('恢复本地草稿 JSON'), { target: { files: [file] } })
  expect(await screen.findByRole('alert')).toHaveTextContent('草稿未恢复'); expect(screen.queryByRole('article', { name: '用户自述简历草稿' })).toBeNull()
  expect(fetcher).not.toHaveBeenCalled(); fetcher.mockRestore()
})
