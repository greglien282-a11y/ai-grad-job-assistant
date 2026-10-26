import { fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import JdLab from './JdLab'
import Root from '../../Root'
import { jdLabEnabled } from './gate'
afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); window.history.replaceState(null, '', '/') })
function start() { fireEvent.click(screen.getByRole('button', { name: '使用合成 JD 样例' })); fireEvent.click(screen.getByRole('button', { name: '分析岗位要求 →' })) }
it('requires the explicit development gate and remains closed in production even with a flag', () => {
  expect(jdLabEnabled()).toBe(false); vi.stubEnv('VITE_PATHWISE_JD_LAB', 'synthetic-v1'); expect(jdLabEnabled()).toBe(true)
  vi.stubEnv('DEV', false); expect(jdLabEnabled()).toBe(false)
  window.history.replaceState(null, '', '/jd-lab'); render(<Root />); expect(screen.getByText('开发预览未启用')).toBeVisible()
})
it('walks from JD to printable original lines and exactly three questions without API or storage', () => {
  const fetcher = vi.fn(); vi.stubGlobal('fetch', fetcher); render(<JdLab />); start()
  const resume = screen.getByRole('article', { name: '可打印简历预览' })
  expect(within(resume).getByText('我测试了3个导出按钮。')).toBeVisible(); expect(within(resume).queryByText('我计划部署服务。')).toBeNull()
  const print = vi.spyOn(window, 'print').mockImplementation(() => undefined)
  fireEvent.click(screen.getByRole('button', { name: '打印预览 / 浏览器保存 PDF' })); expect(print).toHaveBeenCalledOnce(); print.mockRestore()
  fireEvent.click(screen.getByRole('button', { name: '开始三题复习' })); expect(screen.getByText('第 1 / 3 题')).toBeVisible()
  fireEvent.click(screen.getByRole('button', { name: '跳过这题' })); expect(screen.getByText('第 2 / 3 题')).toBeVisible()
  fireEvent.change(screen.getByLabelText('复习回答'), { target: { value: '我记不清数字，需要核对。' } })
  fireEvent.click(screen.getByRole('button', { name: '结束并复盘' })); expect(screen.getByText(/已记录 1 条本地回答/)).toBeVisible()
  expect(fetcher).not.toHaveBeenCalled(); expect(localStorage.length).toBe(0); expect(sessionStorage.length).toBe(0)
})
it('marks fabricated metrics as an unverified draft and removes them from printable content', () => {
  render(<JdLab />); start(); const editor = screen.getAllByLabelText(/本地预览文字 /)[0]
  fireEvent.change(editor, { target: { value: '我提升了99%，掌握Python。' } })
  expect(screen.getByText(/未核实的本地改写/)).toBeVisible()
  expect(within(screen.getByRole('article', { name: '可打印简历预览' })).queryByText(/99%/)).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '恢复原句 1' })); expect(editor).toHaveValue('我测试了3个导出按钮。')
})
it('retains JD quote when manually adjusting a requirement, clears all downstream state after new input', () => {
  render(<JdLab />); start(); const field = screen.getAllByLabelText(/要求描述 jd-/)[0]
  fireEvent.change(field, { target: { value: '手动调整，不是原文' } }); expect(screen.getByText('用户调整，未重新认证 JD 含义')).toBeVisible()
  expect(screen.getByText('软件测试实习生', { selector: 'blockquote' })).toBeVisible()
  fireEvent.change(screen.getByLabelText('岗位 JD 原文'), { target: { value: '' } })
  expect(screen.queryByRole('article', { name: '可打印简历预览' })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '分析岗位要求 →' })); expect(screen.getByRole('alert')).toHaveTextContent('请先粘贴')
})
