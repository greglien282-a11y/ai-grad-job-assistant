import React, { useState } from "react";
import { createRoot } from "react-dom/client";
import { parseBatch } from "../../../g3_choice_protocol/web/contract";
import "./style.css";

const kinds = ["personal_action", "plan", "background", "boundary"] as const;
const stages: Record<string, string[]> = {
  personal_action: ["completed", "in_progress"],
  plan: ["planned", "in_progress"],
  background: ["not_applicable"],
  boundary: ["not_applicable"],
};
const samples = [
  "我部署了服务。",
  "我编写了脚本。",
  "我测试了导出按钮。",
  "我整理了27条缺失记录。",
  "我制作了👩‍💻原型图。",
  "我计划部署服务。",
  "我正在部署服务。",
  "我们部署了服务。",
  "我没有部署服务。",
];
type Parsed = ReturnType<typeof parseBatch>;
type Views = NonNullable<Parsed["view"]>;

function decode(value: unknown): Views {
  const v = value as Record<string, unknown>;
  if (
    !v ||
    typeof v !== "object" ||
    Object.keys(v).sort().join("|") !==
      [
        "demo_contract",
        "scope",
        "operation_id",
        "result",
        "truth_verified",
        "persistence_authorized",
        "facts",
      ]
        .sort()
        .join("|") ||
    v.demo_contract !== "g4-disposable-read-v1" ||
    v.scope !== "DISPOSABLE_RESEARCH_DATABASE" ||
    v.result !== "committed_pending_review" ||
    v.truth_verified !== false ||
    v.persistence_authorized !== false
  )
    throw Error("unsafe_contract");
  const parsed = parseBatch(v.facts);
  if (parsed.status !== "parsed_candidate" || !parsed.view)
    throw Error("unsafe_contract");
  if (
    parsed.view.some(
      (f) =>
        f.subject.status !== "pending" ||
        f.subject.fact_version !== 1 ||
        f.subject.classification_contract !== "explicit-typed-v1" ||
        f.basis.status !== "event_recorded" ||
        !f.basis.event ||
        f.basis.event.operation_id !== v.operation_id,
    )
  )
    throw Error("unsafe_contract");
  return parsed.view;
}

function App() {
  const [content, setContent] = useState(samples[0]);
  const [kind, setKind] = useState("");
  const [stage, setStage] = useState("");
  const [lose, setLose] = useState(false);
  const [key] = useState(() => crypto.randomUUID());
  const [phase, setPhase] = useState("idle");
  const [message, setMessage] = useState(
    "尚未保存。先核对合成原话，再明确选择类型和进度。",
  );
  const [views, setViews] = useState<Views>([]);
  const locked = ["submitting", "unknown", "saved", "unsafe"].includes(phase);
  function editContent(value: string) {
    setContent(value);
    setKind("");
    setStage("");
  }
  async function recover() {
    setViews([]);
    setPhase("submitting");
    setMessage("只读恢复中，不重新提交。");
    try {
      const r = await fetch("/recover", { headers: { "X-Research-Key": key } });
      if (!r.ok) {
        setPhase("unknown");
        setMessage("只读恢复暂不可用。没有重新提交，请保留当前页面。");
        return;
      }
      const data = await r.json();
      const parsed = decode(data);
      setViews(parsed);
      setPhase("saved");
      setMessage("已从一次性 PostgreSQL 只读恢复。事实仍待审核。");
    } catch {
      setPhase("unknown");
      setMessage("网络或读取合同不可用，未重新提交。请保留页面后再只读恢复。");
    }
  }
  async function save() {
    if (locked || !kind || !stage) return;
    setViews([]);
    setPhase("submitting");
    setMessage("受信校验与数据库事务处理中。");
    try {
      const r = await fetch("/candidate", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Research-Key": key },
        body: JSON.stringify({
          demo_contract: "g4-disposable-submit-v1",
          synthetic: true,
          content,
          kind,
          stage,
          lose_response: lose,
        }),
      });
      if (!r.ok) {
        const error = await r.json();
        if (error.code === "demo_not_saved") {
          setPhase("rejected");
          setMessage(
            r.status === 503
              ? "独立校验服务不可用，本次未保存。"
              : "声明或来源未通过受限规则，本次未保存。请核对类型与进度。",
          );
        } else {
          setPhase("unknown");
          setMessage("提交结果尚未核对。请使用只读恢复，不要重新提交。");
        }
        return;
      }
      const data = await r.json();
      try {
        setViews(decode(data));
        setPhase("saved");
        setMessage("已提交到一次性 PostgreSQL；这是用户声明，事实仍待审核。");
      } catch {
        setViews([]);
        setPhase("unsafe");
        setMessage(
          "未知合同或来源不完整，停止展示。请只读恢复，不回退旧接口。",
        );
      }
    } catch {
      setPhase("unknown");
      setMessage("响应丢失，保存结果未知。请只读恢复，不重新提交。");
    }
  }
  return (
    <main>
      <header>
        <p className="eyebrow">PATHWISE · G4-0D · 研究演示</p>
        <h1>原话与选择，分别留证</h1>
        <p>真实一次性 PostgreSQL · 独立校验进程 · 仅限公开合成样例</p>
      </header>
      <aside>
        <strong>不是真实 Pathwise 数据，没有正式 CO3。</strong>{" "}
        不使用生产登录、正式账户或真实招聘资料。关闭演示将清理测试数据。用户声明不等于平台核实；R03
        尚未解决。
      </aside>
      <section>
        <h2>1 · 核对合成原话</h2>
        <label>
          样例
          <select
            aria-label="合成样例"
            disabled={locked}
            value={content}
            onChange={(e) => editContent(e.target.value)}
          >
            {samples.map((x) => (
              <option key={x}>{x}</option>
            ))}
          </select>
        </label>
        <label>
          原话
          <textarea
            aria-label="原话"
            disabled={locked}
            value={content}
            onChange={(e) => editContent(e.target.value)}
          />
        </label>
        <small>
          只接受上述公开合成样例；不自动润色、不增加数字或推断完成。
        </small>
      </section>
      <section>
        <h2>2 · 明确声明</h2>
        <div className="row">
          <label>
            事实类型
            <select
              aria-label="事实类型"
              value={kind}
              disabled={locked}
              onChange={(e) => {
                setKind(e.target.value);
                setStage("");
              }}
            >
              <option value="">请选择事实类型</option>
              {kinds.map((x) => (
                <option key={x}>{x}</option>
              ))}
            </select>
          </label>
          <label>
            进度
            <select
              aria-label="进度"
              value={stage}
              disabled={locked || !kind}
              onChange={(e) => setStage(e.target.value)}
            >
              <option value="">请选择进度</option>
              {(stages[kind] || []).map((x) => (
                <option key={x}>{x}</option>
              ))}
            </select>
          </label>
        </div>
        <p>计划、进行中、团队背景与限制不会默认成为个人已完成成果。</p>
        <label className="check">
          <input
            type="checkbox"
            checked={lose}
            disabled={locked}
            onChange={(e) => setLose(e.target.checked)}
          />
          模拟提交成功后响应丢失
        </label>
        <div className="row">
          <button disabled={locked || !kind || !stage} onClick={save}>
            校验并保存到一次性数据库
          </button>
          <button
            className="secondary"
            disabled={
              phase === "idle" || phase === "submitting" || phase === "rejected"
            }
            onClick={recover}
          >
            只读恢复结果
          </button>
        </div>
        <p role="status" aria-live="polite">
          {message}
        </p>
      </section>
      <section>
        <h2>3 · 待审核与来源追溯</h2>
        {views.length === 0 ? (
          <p>没有可安全展示的已提交结果。</p>
        ) : (
          views.map((v) => (
            <article key={v.subject.fact_id}>
              <span className="badge">pending · 用户声明 · 未核实</span>
              <h3>{v.subject.statement}</h3>
              <p>
                {v.subject.fact_kind} / {v.subject.progress_stage}
              </p>
              <dl>
                <dt>原始 User Turn</dt>
                <dd>{v.turns[0].content}</dd>
                <dt>原始与当前文字引用（code-point 半开区间）</dt>
                <dd>
                  {v.text_provenance.current.map((c) => (
                    <p key={c.start}>
                      [{c.start}, {c.end}) “{c.quote}”
                    </p>
                  ))}
                </dd>
                <dt>不可变分类选择事件</dt>
                <dd>{v.basis.event?.id}</dd>
                <dt>分类依据</dt>
                <dd>已记录明确选择；有限规则相符。没有平台真实性认证。</dd>
              </dl>
            </article>
          ))
        )}
      </section>
      <footer>
        本地研究端口，不连接正式业务接口／Provider。只读恢复不会创建第二份事实或操作。
      </footer>
    </main>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
