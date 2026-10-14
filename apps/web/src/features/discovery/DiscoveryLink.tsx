import type { MouseEvent, ReactNode } from 'react'

export function DiscoveryLink({ href, children, ...props }: { href: '/discovery' | '/discovery/summary'; children: ReactNode; className?: string; 'aria-current'?: 'step' }) {
  function follow(event: MouseEvent<HTMLAnchorElement>) {
    if (event.button || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return
    event.preventDefault()
    window.history.pushState(null, '', href)
    window.dispatchEvent(new PopStateEvent('popstate'))
  }
  return <a href={href} onClick={follow} {...props}>{children}</a>
}
