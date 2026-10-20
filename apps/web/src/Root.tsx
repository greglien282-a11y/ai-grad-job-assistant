import App from './App'
import DiscoveryWorkbench from './features/discovery/DiscoveryWorkbench'
import Home from './features/Home'
import TypedRead from './features/typed-read/TypedRead'
import { useEffect, useState } from 'react'
const currentPath = () => window.location.pathname.replace(/\/+$/, '') || '/'
export default function Root() {
  const [path, setPath] = useState(currentPath)
  useEffect(() => {
    const update = () => setPath(currentPath())
    window.addEventListener('popstate', update)
    return () => window.removeEventListener('popstate', update)
  }, [])
  if (path === '/discovery' || path === '/discovery/summary') return <DiscoveryWorkbench view={path.endsWith('/summary') ? 'summary' : 'workspace'} />
  if (path === '/manual') return <App />
  if (path === '/typed-read') return <TypedRead />
  return <Home />
}
