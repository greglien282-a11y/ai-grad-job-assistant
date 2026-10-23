import React, { useReducer, useState } from "react";
import { createRoot } from "react-dom/client";
import { basisLabel } from "../../declaration_read/web/contract";
import {
  initial,
  transition,
  kinds,
  stages,
  stageLabels,
  contributionPreview,
  historyFixture,
  riskReason,
  type Kind,
  type Journey,
} from "./journey";
import samples from "./scenarios.json";
import "./style.css";

function App() {
  const [state, dispatch] = useReducer(
    (
      s: Journey,
      e:
        | Parameters<typeof transition>[1]
        | {
            type: "fixture";
            raw: string;
            risk: boolean;
            responsibility: boolean;
          },
    ) => {
      if (e.type !== "fixture") return transition(s, e);
      const history = structuredClone(historyFixture);
      if (e.responsibility) {
        history.original = history.current = "我们部署了服务。";
        history.snapshots = [
          { statement: history.original, status: "rejected" },
          { statement: history.current, status: "pending" },
        ];
      }
      return { ...initial(e.risk ? history : null), raw: e.raw };
    },
    initial(),
  );
  const [explanation, setExplanation] = useState("");
  const [evidence, setEvidence] = useState("");
  const [fault, setFault] = useState<
    "none" | "before_mock_result" | "after_mock_result"
  >("none");
  const view = state.view;
  const declaration = view?.basis.declaration;
  return (
    <>
      <header>
        <a className="brand" href="/">
          P<span>Pathwise</span>
        </a>
        <span className="version">RESEARCH / G2</span>
        <span className="pill">合成演示 · 未保存</span>
      </header>
      <div className="notice">
        独立交互原型：仅浏览器内存。没有连接正式工作台、数据库、模型或 typed
        写入接口；刷新即丢失。
      </div>
      <main>
        <div className="intro">
          <div>
            <div className="eyebrow">把经历说清楚，再谈成果</div>
            <h1>让每一个事实，都能回到原话。</h1>
            <p>分类由你声明。来源供你核对。审核与真实性认证分别表达。</p>
          </div>
          <div className="count">
            <strong>0</strong>数据库写入
            <br />
            <strong>0</strong>模型调用
          </div>
        </div>
        <nav aria-label="录入旅程">
          <span>01 原话</span>
          <span>02 分类与来源</span>
          <span>03 审核与澄清</span>
          <span>04 结果与恢复</span>
        </nav>
        <div className="grid">
          <section className="card input-card">
            <div className="section-number">01 / 原话</div>
            <h2>从一段真实表述开始</h2>
            <p>请只使用合成样本。系统不会替你改写或补全。</p>
            <label htmlFor="raw">经历原话</label>
            <textarea
              id="raw"
              value={state.raw}
              maxLength={1000}
              onChange={(e) => dispatch({ type: "raw", value: e.target.value })}
              placeholder="选择下方合成样本，再明确选择类型与阶段。"
            />
            <div className="muted">
              {Array.from(state.raw).length} code points · 原样保留
            </div>
            <h3>普通合成样本</h3>
            <div className="samples">
              {samples.slice(0, 7).map((s) => (
                <button
                  key={s.id}
                  className="sample"
                  onClick={() => {
                    setExplanation("");
                    setEvidence("");
                    dispatch({
                      type: "fixture",
                      raw: s.text,
                      risk: false,
                      responsibility: false,
                    });
                  }}
                >
                  {s.label}
                </button>
              ))}
            </div>
            <h3>R03 对抗情景</h3>
            <p className="small">
              加载不同的虚构场景会重开演示，不代表清除了真实会话历史。
            </p>
            <div className="samples">
              {samples.slice(7).map((s) => (
                <button
                  key={s.id}
                  className="sample risk"
                  onClick={() => {
                    setExplanation("");
                    setEvidence("");
                    dispatch({
                      type: "fixture",
                      raw: s.text,
                      risk: true,
                      responsibility: s.id === "team_to_person",
                    });
                  }}
                >
                  {s.label}
                </button>
              ))}
              <button
                className="sample risk"
                onClick={() =>
                  dispatch({
                    type: "fixture",
                    raw: "我整理了27条缺失记录。",
                    risk: true,
                    responsibility: false,
                  })
                }
              >
                无关贡献被阻断
              </button>
            </div>
          </section>
          <section className="card">
            <div className="section-number">02 / 分类与来源</div>
            <h2>明确声明，不代替认证</h2>
            <label htmlFor="kind">事实类型</label>
            <select
              id="kind"
              value={state.kind}
              onChange={(e) =>
                dispatch({ type: "kind", value: e.target.value as Kind })
              }
            >
              <option value="" disabled>
                请明确选择
              </option>
              {Object.entries(kinds).map(([key, value]) => (
                <option key={key} value={key}>
                  {value}
                </option>
              ))}
            </select>
            <label htmlFor="stage">进度阶段</label>
            <select
              id="stage"
              value={state.stage}
              disabled={!state.kind}
              onChange={(e) =>
                dispatch({ type: "stage", value: e.target.value })
              }
            >
              <option value="" disabled>
                请明确选择
              </option>
              {state.kind &&
                stages[state.kind].map((stage) => (
                  <option key={stage} value={stage}>
                    {stageLabels[stage]}
                  </option>
                ))}
            </select>
            <p className="small">
              不会默认选为个人已完成成果。类型、进度、审核状态彼此独立。
            </p>
            <button
              className="primary"
              disabled={!state.raw || !state.kind || !state.stage}
              onClick={() => dispatch({ type: "prepare" })}
            >
              查看候选与来源
            </button>
            {state.error && (
              <p role="alert" className="error">
                {state.error}
              </p>
            )}
            {view ? (
              <div className="source-panel" aria-label="候选来源">
                <span className="badge">待审核 · 合成 v1</span>
                <blockquote>{view.subject.statement}</blockquote>
                <details open>
                  <summary>查看三种来源</summary>
                  <dl>
                    <dt>原始建档原话 / synthetic Turn 4</dt>
                    <dd>{view.turns[0].content}</dd>
                    <dt>当前文字来源 / code-point 半开区间</dt>
                    <dd>
                      <code>[0, {Array.from(state.raw).length})</code>「
                      {view.text_provenance.current.citations[0].quote}」
                    </dd>
                    <dt>独立分类选择来源 / synthetic Turn 6</dt>
                    <dd>{declaration?.declaration_source.quote}</dd>
                  </dl>
                </details>
                <div className="basis">
                  {basisLabel(view)}
                  <br />
                  <small>
                    预先校验的合成样本；浏览器未重新执行
                    c3a。非真实保存的分类依据。
                  </small>
                </div>
              </div>
            ) : (
              <div className="empty">
                选择类型和阶段后核对完整原话与来源。
                <p>
                  旧事实若无分类记录，始终显示“暂无分类依据记录”，不会从建档来源补造。
                </p>
              </div>
            )}
          </section>
        </div>
        <div className="grid lower">
          <section className="card">
            <div className="section-number">03 / 审核与澄清</div>
            <h2>先核对，再留下疑问</h2>
            <button
              disabled={!view || state.reviewed}
              onClick={() => dispatch({ type: "review" })}
            >
              模拟用户审核（不保存）
            </button>
            <p data-testid="review-status">
              {state.reviewed
                ? "已模拟用户确认；不代表平台独立认证。"
                : "待审核；分类声明不会自动确认事实。"}
            </p>
            <div className="qualification" data-testid="qualification">
              {contributionPreview(state)
                ? "模拟正文预览资格：本人动作 / 已完成 / 用户确认。仍未保存。"
                : "当前不进入已完成个人贡献正文。计划、进行中、背景和限制不因此升级。"}
            </div>
            {state.history ? (
              <div className="conflict">
                <span className="badge warn">R03 · 尚未证明独立</span>
                <h3>冲突事实 {state.history.factId}</h3>
                <p>原始拒绝表述：「{state.history.original}」</p>
                <p>
                  当前版本 {state.history.version} 已是 pending，原拒绝仍保留。
                </p>
                <ol>
                  {state.history.snapshots.map((h, i) => (
                    <li key={i}>
                      {h.status}：「{h.statement}」
                    </li>
                  ))}
                </ol>
                <p>
                  {state.history.original.startsWith("我们")
                    ? "从团队表述变为本人动作，只改变责任归属不能证明独立贡献。"
                    : riskReason(state)}
                </p>
                <label htmlFor="explanation">补充解释</label>
                <textarea
                  id="explanation"
                  value={explanation}
                  maxLength={2000}
                  onChange={(e) => setExplanation(e.target.value)}
                />
                <label htmlFor="evidence">
                  额外证据描述（未核实，不访问链接）
                </label>
                <textarea
                  id="evidence"
                  value={evidence}
                  maxLength={2000}
                  onChange={(e) => setEvidence(e.target.value)}
                />
                <button
                  disabled={!explanation.trim() || !evidence.trim()}
                  onClick={() => {
                    dispatch({
                      type: "explain",
                      text: explanation,
                      evidence,
                      revision: state.revision,
                    });
                    setExplanation("");
                    setEvidence("");
                  }}
                >
                  追加解释，继续等待独立审核
                </button>
                <ol aria-label="解释记录">
                  {state.explanations.map((e, i) => (
                    <li key={i}>
                      <strong>解释 {i + 1}：</strong>
                      {e.text}
                      <br />
                      证据描述：{e.evidence}
                    </li>
                  ))}
                </ol>
                <p>解释和证据描述不会自动解锁保存。拒绝历史没有被删除。</p>
              </div>
            ) : (
              <p className="muted">
                此情景未载入拒绝历史；没有冲突提示也不代表语义独立已被证明。
              </p>
            )}
          </section>
          <section className="card">
            <div className="section-number">04 / 结果与恢复</div>
            <h2>遇到中断，不重复提交</h2>
            <p>
              下面只模拟内存中的结果与响应丢失。不会创建正式操作键或 CO 回执。
            </p>
            <label htmlFor="fault">模拟故障点</label>
            <select
              id="fault"
              value={fault}
              onChange={(e) => setFault(e.target.value as typeof fault)}
            >
              <option value="none">无故障</option>
              <option value="before_mock_result">生成模拟结果前中断</option>
              <option value="after_mock_result">生成模拟结果后丢失响应</option>
            </select>
            <div className="actions">
              <button
                disabled={!view}
                onClick={() => dispatch({ type: "attempt", fault })}
              >
                模拟操作结果（不保存）
              </button>
              <button onClick={() => dispatch({ type: "recover" })}>
                只查看内存恢复结果
              </button>
            </div>
            <div role="status" className="result">
              {state.outcome === "idle"
                ? "尚无模拟操作。"
                : state.outcome === "response_unknown"
                  ? "模拟响应未知；请只查看恢复结果，不自动重发。数据库未保存。"
                  : state.outcome === "mock_recovered"
                    ? `内存模拟结果 ${state.mockReceipt}；不是持久回执，资料未保存。`
                    : "未保存；没有可恢复的正式回执，需后续事务审核与政策批准。"}
            </div>
            <details>
              <summary>查看本次内存操作记录</summary>
              <ol>
                {state.actions.map((a, i) => (
                  <li key={i}>{a}</li>
                ))}
              </ol>
            </details>
            <div className="boundary">
              <strong>真实性认证：未进行</strong>
              <br />
              持久化授权：没有
              <br />
              分类依据写入：未实现
              <br />
              正式 typed writer：保持关闭
            </div>
          </section>
        </div>
        <footer>
          G2 隔离研究原型 · 技术备份、正式简历与生产审核均未在这里生成。R03 / D4
          / D5 / D6 剩余 / D8 继续 BLOCK。
        </footer>
      </main>
    </>
  );
}
createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
