import App from './App'
import DiscoveryWorkbench from './features/discovery/DiscoveryWorkbench'
import Home from './features/Home'
export default function Root() {
  const path = window.location.pathname.replace(/\/+$/, '') || '/'
  if (path === '/discovery') return <DiscoveryWorkbench />
  if (path === '/manual') return <App />
  return <Home />
}
