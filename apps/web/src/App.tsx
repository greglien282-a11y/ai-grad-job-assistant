import { useEffect, useState } from 'react'
import { getHealth } from './lib/api'

type ConnectionState = 'checking' | 'connected' | 'error'

export default function App() {
  const [connection, setConnection] = useState<ConnectionState>('checking')
  const [error, setError] = useState('')

  async function checkConnection() {
    setConnection('checking')
    setError('')
    try {
      await getHealth()
      setConnection('connected')
    } catch (cause) {
      setConnection('error')
      setError(cause instanceof Error ? cause.message : '未知错误')
    }
  }

  useEffect(() => {
    void checkConnection()
  }, [])

  return (
    <div className="page">
      <header className="header">
        <a className="brand" href="https://greglien282-a11y.github.io/ai-grad-job-assistant/">
          <span className="brand-symbol" aria-hidden="true">✦</span>
          启程 <span className="brand-en">Pathwise</span>
        </a>
        <span className="stage">M1-0 · Engineering foundation</span>
      </header>
      <main className="main">
        <p className="eyebrow">AI GRADUATE JOB ASSISTANT</p>
        <h1>从交互原型，迈向真正的 AI 产品。</h1>
        <p className="intro">这是 Pathwise 的正式应用工程骨架。目前只验证 React 前端和 FastAPI 后端的连接，经历挖掘与岗位定制尚未接入真实 AI。</p>
        <section className="status-card" aria-live="polite">
          <div>
            <p className="status-label">后端 API 连接状态</p>
            <p className="status-value">
              <span className={`status-dot ${connection}`} aria-hidden="true" />
              {connection === 'checking' ? '正在连接…' : connection === 'connected' ? '连接成功 · API 正常' : '暂时无法连接'}
            </p>
            {connection === 'error' && (
              <p className="status-hint">请确认 FastAPI 已启动：127.0.0.1:8000。详细信息：{error}</p>
            )}
          </div>
          <button type="button" onClick={() => void checkConnection()} disabled={connection === 'checking'}>
            重新检查
          </button>
        </section>
        <div className="milestones">
          <span>✓ 前端工程骨架</span>
          <span>✓ API 健康检查</span>
          <span>○ 真实经历库（下一阶段）</span>
          <span>○ AI 经历挖掘（下一阶段）</span>
        </div>
        <p className="footnote">已上线的 V2 交互原型保持独立，不受本工程开发影响。</p>
      </main>
    </div>
  )
}
