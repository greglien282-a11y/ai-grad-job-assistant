import App from './App'
import DiscoveryWorkbench from './features/discovery/DiscoveryWorkbench'
import Home from './features/Home'
import TypedRead from './features/typed-read/TypedRead'
import { lazy, Suspense, useEffect, useState } from 'react'
import { jdLabEnabled } from './features/jd-lab/gate'
const JdLab = lazy(() => import('./features/jd-lab/JdLab'))
const LocalResumeLab = lazy(() => import('./features/resume-lab/LocalResumeLab'))
const currentPath = () => window.location.pathname.replace(/\/+$/, '') || '/'
export default function Root() {
  const [path, setPath] = useState(currentPath)
  useEffect(() => {
    const update = () => setPath(currentPath())
    window.addEventListener('popstate', update)
    return () => window.removeEventListener('popstate', update)
  }, [])
  if (path === '/jd-lab') return jdLabEnabled() ? <Suspense fallback={<p>正在载入本地预览…</p>}><JdLab /></Suspense> : <main><h1>开发预览未启用</h1><p>此入口仅供显式启用的本地合成测试，生产构建不可访问。</p><a href="/">返回首页</a></main>
  if (path === '/resume-lab') return jdLabEnabled() ? <Suspense fallback={<p>正在载入本地工作台…</p>}><LocalResumeLab /></Suspense> : <main><h1>本地简历实验未启用</h1><p>需要显式开发门禁；生产构建不可访问。</p><a href="/">返回首页</a></main>
  if (path === '/discovery' || path === '/discovery/summary') return <DiscoveryWorkbench view={path.endsWith('/summary') ? 'summary' : 'workspace'} />
  if (path === '/manual') return <App />
  if (path === '/typed-read') return <TypedRead />
  return <Home />
}
