import App from './App'
import DiscoveryWorkbench from './features/discovery/DiscoveryWorkbench'
function Entries() {
  return <section className="entry-chooser" aria-label="三个首页入口"><h2>你想从哪里开始？</h2><div className="entry-grid"><div>我已经有简历<small>简历导入尚未实现 · 开发中</small></div><a href="/discovery">我还没有一份像样的简历<small>进入真实事实库的合成对话工作台 →</small></a><div>我找到了一份目标岗位<small>岗位分析尚未实现 · 开发中</small></div></div><p>下方是兼容的手工事实工作台，也可直接从一句描述开始。真实 AI 未启用。</p></section>
}
export default function Root() {
  const path = window.location.pathname.replace(/\/+$/, '') || '/'
  return path === '/discovery' ? <DiscoveryWorkbench /> : <App intro={path === '/manual' ? undefined : <Entries />} />
}
