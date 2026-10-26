import { useState } from 'react'
import ResumeWorkbench from './ResumeWorkbench'
import type { Workbench } from './import'
import './resume.css'

export default function LocalResumeLab() {
  const [workbench, setWorkbench] = useState<Workbench | null>(null)
  return <div className="resume-lab"><header><a href="/">✦ Pathwise</a><span>本地简历工作台 · 开发预览</span><a href="/jd-lab">合成可信预览（独立入口）</a></header><main>
    <section className="resume-hero"><p className="resume-kicker">YOUR WORDS. YOUR NEXT STEP.</p><h1>从你已有的经历，<br />走向下一份岗位。</h1><p>没有亮眼指标也能开始。先保留原话，再看清证据与边界。</p></section>
    <aside className="resume-notice">本地材料和手工声明均未经平台核实；不自动确认、分类或保存到事实库。合成已审核FactV3仅在原独立实验入口，不可与导入文字混淆。正式数据库与认证结果未接入；无网络、AI或G4正式写入。</aside>
    <ResumeWorkbench value={workbench} onChange={setWorkbench} />
  </main></div>
}
