import { render, screen } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import Root from './Root'

afterEach(() => window.history.replaceState(null, '', '/'))
it('root focuses on three established entries without mounting a workbench', () => {
  window.history.replaceState(null, '', '/')
  render(<Root />)
  expect(screen.getByRole('region', { name: '三个首页入口' })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: /我还没有一份像样的简历/ })).toHaveAttribute('href', '/discovery')
  expect(screen.getByText('简历导入 · 开发中')).toBeInTheDocument()
  expect(screen.getByText('岗位分析 · 开发中')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: '手工工作台 · 兼容入口' })).toHaveAttribute('href', '/manual')
  expect(screen.queryByLabelText('原始经历')).not.toBeInTheDocument()
  expect(screen.queryByLabelText('描述一段经历')).not.toBeInTheDocument()
})
it('manual retains the original business workbench on its compatibility route', () => {
  window.history.replaceState(null, '', '/manual')
  render(<Root />)
  expect(screen.getByLabelText('原始经历')).toBeInTheDocument()
  expect(screen.queryByRole('region', { name: '三个首页入口' })).not.toBeInTheDocument()
})
