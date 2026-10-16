import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'
import { QuestionCard } from './QuestionCard'
const q = { id: '00000000-0000-4000-8000-000000000001', state: 'active' as const, version: 1, content: 'Synthetic question about your own work?' }
it('question selection and cancelled deletion are explicit', async () => {
  const onSelect = vi.fn(), onAction = vi.fn(async () => true)
  render(<QuestionCard question={q} current selected={false} disabled={false} onSelect={onSelect} onAction={onAction} />)
  await userEvent.click(screen.getByRole('checkbox'))
  expect(onSelect).toHaveBeenCalledOnce()
  await userEvent.click(screen.getByText('问题选项 · 跳过、纠正或隐藏'))
  await userEvent.click(screen.getByRole('button', { name: '删除问题' }))
  await userEvent.click(screen.getByRole('button', { name: '取消删除问题' }))
  expect(onAction).not.toHaveBeenCalled()
})
it('retains a correction draft on newer question version until explicit review', async () => {
  const onAction = vi.fn(async () => true), props = { current: true, selected: false, disabled: false, onSelect: vi.fn(), onAction }
  const view = render(<QuestionCard question={q} {...props} />)
  await userEvent.click(screen.getByText('问题选项 · 跳过、纠正或隐藏'))
  await userEvent.click(screen.getByRole('button', { name: '纠正问题' }))
  fireEvent.change(screen.getByLabelText('纠正后的问题'), { target: { value: 'Synthetic retained question draft' } })
  view.rerender(<QuestionCard question={{ ...q, version: 2, content: 'Synthetic changed by another client?' }} {...props} />)
  expect(screen.getByLabelText('纠正后的问题')).toHaveValue('Synthetic retained question draft')
  expect(screen.getByRole('button', { name: '保存问题纠正' })).toBeDisabled()
  await userEvent.click(screen.getByRole('button', { name: '我已核对最新问题版本' }))
  await userEvent.click(screen.getByRole('button', { name: '保存问题纠正' }))
  expect(onAction).toHaveBeenCalledWith('correct', 'Synthetic retained question draft')
})
it('hidden and deleted questions do not show private question content or selection', () => {
  const props = { current: true, selected: false, disabled: false, onSelect: vi.fn(), onAnswer: vi.fn(), onAction: vi.fn(async () => true) }
  const view = render(<QuestionCard question={{ ...q, state: 'hidden' }} {...props} />)
  expect(screen.queryByText(q.content)).not.toBeInTheDocument()
  expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: '回答这题' })).not.toBeInTheDocument()
  view.rerender(<QuestionCard question={{ ...q, state: 'deleted', content: null }} {...props} />)
  expect(screen.queryByText(q.content)).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: '纠正问题' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: '回答这题' })).not.toBeInTheDocument()
  expect(screen.getByText('问题版本 1')).toBeVisible()
})
