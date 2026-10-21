import { UPGRADE_MESSAGE } from '../../lib/experience'

export function UpgradeNotice() {
  return <main className="result-shell" data-contract-state="upgrade_required">
    <h1>当前会话需要新版读取</h1>
    <p className="alert" role="alert">{UPGRADE_MESSAGE}</p>
    <p>旧工作台的审核、编辑、回答、整理、管理和导出已停止，先前展示的正文与来源已清空。</p>
    <p>已有操作键和待恢复记录保留；本页不会换键、重发、清除记录或自动跳转。</p>
    <a href="/typed-read">由我进入新版只读页面</a>
    <p>进入后需手动填写会话资料和凭证。凭证不会放入链接，也不会从旧工作台自动传递。</p>
    <p>新版读取若暂不可用，会明确提示，不会回退旧接口。</p>
  </main>
}
