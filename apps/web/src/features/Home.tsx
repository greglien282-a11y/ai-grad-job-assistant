import './Home.css'
import { jdLabEnabled } from './jd-lab/gate'

export default function Home() {
  return <div className="home">
    <header className="home-header"><a className="brand" href="/">✦ 启程 <span>Pathwise</span></a><a href="/manual">手工工作台 · 兼容入口</a></header>
    <main className="home-main">
      <p className="home-kicker">PATHWISE · 从真实经历开始</p>
      <h1>你的下一步，<br />从这里启程。</h1>
      <p className="home-lead">无论你从哪里开始，都让做过的事成为求职的底气。</p>
      <section aria-label="三个首页入口" className="home-entries">
        <h2>你想从哪里开始？</h2>
        <div className="home-grid">
          {jdLabEnabled() ? <a className="home-entry home-primary" href="/resume-lab"><span className="home-step">01 · 路径 A</span><h3>我已经有简历</h3><p>本地文本导入 → 原文与来源逐段核对</p><span className="home-action">打开本地简历工作台 →</span></a> : <article className="home-entry"><span className="home-step">01 · 路径 A</span><h3>我已经有简历</h3><p>从已有简历开始整理。</p><span className="home-unavailable">简历导入 · 开发中</span></article>}
          <a className="home-entry home-primary" href="/discovery"><span className="home-step">02 · 路径 B</span><h3>我还没有一份像样的简历</h3><p>先说一段经历，再逐条核对事实。</p><span className="home-action">开始整理经历 →</span></a>
          {jdLabEnabled() ? <a className="home-entry home-primary" href="/jd-lab"><span className="home-step">03 · 路径 C</span><h3>我找到了一份目标岗位</h3><p>岗位要求 → 原话匹配 → 简历预览 → 三题复习</p><span className="home-action">打开本地合成预览 →</span></a> : <article className="home-entry"><span className="home-step">03 · 路径 C</span><h3>我找到了一份目标岗位</h3><p>从目标岗位开始准备。</p><span className="home-unavailable">岗位分析 · 开发中</span></article>}
        </div>
      </section>
      <p className="home-mode">当前路径 B 使用零费用合成测试模式，固定追问不代表真实 AI 自适应能力。请仅使用合成资料体验。</p>
    </main>
  </div>
}
