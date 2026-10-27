import { fireEvent, render, screen, within } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import JdLab from './JdLab'
import { sample } from './fixtures'
import type { LabInput } from './policy'

const fixture = vi.hoisted(() => ({ rows: [] as LabInput[] }))
vi.mock('./fixtures', async importOriginal => ({
  ...await importOriginal<typeof import('./fixtures')>(),
  get samples() { return fixture.rows },
}))

it.each(['pending', 'rejected', 'lawful_duplicate'] as const)('keeps actual printable admission stable across %s permutations', state => {
  const text = '我测试了3个导出按钮。'
  const confirmed = sample(80, text)
  const other = sample(81, text, 'personal_action', 'completed', state === 'lawful_duplicate' ? 'user_confirmed' : state)
  const outcomes: string[][] = []
  for (const rows of [[other, confirmed], [confirmed, other]]) {
    fixture.rows = rows
    const view = render(<JdLab />)
    fireEvent.click(screen.getByRole('button', { name: '使用合成 JD 样例' }))
    fireEvent.click(screen.getByRole('button', { name: '分析岗位要求 →' }))
    const printed = within(screen.getByRole('article', { name: '可打印简历预览' }))
    outcomes.push(printed.queryAllByRole('listitem').map(li => li.textContent ?? ''))
    const button = screen.getByRole('button', { name: '打印预览 / 浏览器保存 PDF' })
    if (state === 'lawful_duplicate') expect(button).toBeEnabled()
    else expect(button).toBeDisabled()
    view.unmount()
  }
  const expected = state === 'lawful_duplicate' ? [text] : []
  expect(outcomes).toEqual([expected, expected])
})
