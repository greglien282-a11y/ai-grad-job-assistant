import {
  parse,
  type Classification,
  type Envelope,
} from "../../declaration_read/web/contract";
import samples from "./scenarios.json";

export const kinds = {
  personal_action: "本人动作",
  plan: "计划",
  background: "团队 / 项目背景",
  boundary: "个人限制",
} as const;
export type Kind = keyof typeof kinds;
export const stages: Record<Kind, string[]> = {
  personal_action: ["in_progress", "completed"],
  plan: ["planned", "in_progress"],
  background: ["not_applicable"],
  boundary: ["not_applicable"],
};
export const stageLabels: Record<string, string> = {
  in_progress: "进行中",
  completed: "已完成（用户声明）",
  planned: "计划中",
  not_applicable: "不适用",
};
export type RejectedHistory = {
  factId: string;
  version: number;
  original: string;
  current: string;
  snapshots: { statement: string; status: string }[];
};
export const historyFixture: RejectedHistory = {
  factId: "synthetic-history-1",
  version: 2,
  original: "我测试了3个导出按钮。",
  current: "我测试了3个导出按钮。",
  snapshots: [
    { statement: "我测试了3个导出按钮。", status: "rejected" },
    { statement: "我测试了3个导出按钮。", status: "pending" },
  ],
};
export const readFaultLabels = {
  unknown_contract: "未知读取合同版本（模拟）",
  missing_source: "原话来源缺失（模拟）",
  missing_basis: "分类依据字段缺失（模拟）",
  conflict_409: "409 上下文冲突（模拟）",
  unavailable_503: "503 读取暂不可用（模拟）",
  offline: "断网（模拟）",
} as const;
export type ReadFault = keyof typeof readFaultLabels;
export type Fault =
  | "none"
  | "before_mock_result"
  | "after_mock_result"
  | ReadFault;
export const readFailureMessages: Record<ReadFault, string> = {
  unknown_contract:
    "模拟读取合同版本不受支持；已拒绝投影，不降级读取，未保存。",
  missing_source: "模拟原话来源缺失；无法完整核对来源，已拒绝投影，未保存。",
  missing_basis: "模拟分类依据字段缺失；读包不完整，不补造依据，未保存。",
  conflict_409: "模拟 409 上下文版本冲突；旧投影已隐藏，需重新核对，未保存。",
  unavailable_503: "模拟 503 读取暂不可用；无法取得完整投影，未保存。",
  offline: "模拟断网；无法取得完整读取结果，不自动重试，未保存。",
};
type ReadFailure = {
  kind: ReadFault;
  parserCode: string | null;
  truth_verified: false;
  persistence_authorized: false;
};
export type Journey = {
  raw: string;
  kind: Kind | "";
  stage: string;
  view: Envelope | null;
  error: string;
  reviewed: boolean;
  history: RejectedHistory | null;
  explanations: { text: string; evidence: string }[];
  revision: number;
  outcome:
    | "idle"
    | "not_saved"
    | "response_unknown"
    | "mock_recovered"
    | "read_failed";
  readFailure: ReadFailure | null;
  mockReceipt: string | null;
  actions: string[];
};
export function initial(history: RejectedHistory | null = null): Journey {
  return {
    raw: "",
    kind: "",
    stage: "",
    view: null,
    error: "",
    reviewed: false,
    history: structuredClone(history),
    explanations: [],
    revision: 1,
    outcome: "idle",
    readFailure: null,
    mockReceipt: null,
    actions: [],
  };
}
const uuid = (n: number) =>
  `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
export function candidate(
  raw: string,
  kind: Kind,
  stage: string,
): Envelope | null {
  if (!stages[kind].includes(stage)) return null;
  const classification: Classification = {
    fact_kind: kind,
    progress_stage: stage as Classification["progress_stage"],
    classification_contract: "explicit-typed-v1",
  };
  const citation = {
    turn_id: uuid(4),
    start: 0,
    end: Array.from(raw).length,
    quote: raw,
  };
  const group = {
    availability: "exact_quotes",
    turn_ids: [uuid(4)],
    citations: [citation],
  };
  // This is a synthetic choice source, not an inserted Turn or real basis.
  const choice = `我选择事实类型为 ${kind}，进度为 ${stage}。`;
  const envelope = {
    read_contract: "classification-declaration-read-candidate-v1",
    synthetic: true,
    subject: {
      fact_id: uuid(3),
      session_id: uuid(1),
      project_id: uuid(2),
      fact_version: 1,
      statement: raw,
      status: "pending",
      ...classification,
    },
    turns: [
      { id: uuid(4), session_id: uuid(1), role: "user", content: raw },
      { id: uuid(6), session_id: uuid(1), role: "user", content: choice },
    ],
    text_provenance: { original: group, current: structuredClone(group) },
    basis: {
      status: "user_declaration_recorded",
      declaration: {
        declaration_contract:
          "explicit-user-classification-declaration-candidate-v1",
        declaration_id: uuid(5),
        record_type: "explicit_user_choice",
        actor: "user",
        fact_id: uuid(3),
        session_id: uuid(1),
        project_id: uuid(2),
        fact_version: 1,
        classification,
        statement_citations: [structuredClone(citation)],
        declaration_source: {
          turn_id: uuid(6),
          start: 0,
          end: Array.from(choice).length,
          quote: choice,
        },
        recorded_at: "2026-10-23T00:00:00Z",
        recorded_validation: {
          contract: "typed-semantic-spike-v1",
          status: "eligible_candidate",
          code: "finite_rule_match",
        },
      },
    },
  };
  // Only exact prevalidated synthetic fixture triples may claim this mock record.
  // Arbitrary text stays unsupported; there is no browser lexical classifier.
  if (
    !samples.some((s) => s.text === raw && s.kind === kind && s.stage === stage)
  )
    return null;
  return parse(envelope).view;
}
export type Event =
  | { type: "raw"; value: string }
  | { type: "kind"; value: Kind }
  | { type: "stage"; value: string }
  | { type: "prepare" }
  | { type: "review" }
  | { type: "explain"; text: string; evidence: string; revision: number }
  | {
      type: "attempt";
      fault: Fault;
    }
  | { type: "recover" };
export function transition(previous: Journey, event: Event): Journey {
  const s = structuredClone(previous);
  // Keep a failed-read veto for this synthetic scenario. Regenerating a local
  // candidate or switching the fault selector is not a valid read/fallback.
  if (
    s.readFailure &&
    ["prepare", "review", "attempt", "recover"].includes(event.type)
  ) {
    s.actions.push(`${event.type}_blocked`);
    return s;
  }
  const clear = () => {
    s.view = null;
    s.reviewed = false;
    s.error = s.readFailure ? readFailureMessages[s.readFailure.kind] : "";
    s.outcome = s.readFailure ? "read_failed" : "idle";
    if (!s.readFailure) s.mockReceipt = null;
  };
  if (event.type === "raw") {
    clear();
    s.raw = event.value;
    s.kind = "";
    s.stage = "";
  }
  if (event.type === "kind") {
    clear();
    s.kind = event.value;
    s.stage = "";
  }
  if (event.type === "stage") {
    clear();
    s.stage = event.value;
  }
  if (event.type === "prepare") {
    clear();
    s.view = s.kind ? candidate(s.raw, s.kind, s.stage) : null;
    if (!s.view)
      s.error = "此原话与分类组合不在已验证的合成样本内；需要澄清，未保存。";
  }
  if (event.type === "review" && s.view) {
    s.reviewed = true;
  }
  if (event.type === "explain") {
    const valid = (v: string) =>
      !!v.trim() &&
      Array.from(v).length <= 2000 &&
      !v.includes("\0") &&
      Array.from(v).every(
        (cp) =>
          cp.length !== 1 ||
          cp.charCodeAt(0) < 0xd800 ||
          cp.charCodeAt(0) > 0xdfff,
      );
    if (
      event.revision !== s.revision ||
      !s.history ||
      !valid(event.text) ||
      !valid(event.evidence)
    ) {
      s.error = "解释版本或内容无效，未保存。";
    } else {
      s.explanations.push({ text: event.text, evidence: event.evidence });
      s.revision++;
      s.error = s.readFailure ? readFailureMessages[s.readFailure.kind] : "";
    }
  }
  if (event.type === "attempt") {
    if (Object.hasOwn(readFaultLabels, event.fault)) {
      const kind = event.fault as ReadFault;
      let parserCode: string | null = null;
      if (
        kind === "unknown_contract" ||
        kind === "missing_source" ||
        kind === "missing_basis"
      ) {
        // Mutate a COPY of the synthetic response, then use the unchanged G2.1
        // strict parser. Never fall back to the prior/locally rebuilt view.
        const payload: Record<string, unknown> = { ...structuredClone(s.view) };
        if (kind === "unknown_contract")
          payload.read_contract =
            "classification-declaration-read-candidate-v999";
        if (kind === "missing_source" && s.view)
          payload.turns = s.view.turns.filter(
            (turn) =>
              !s.view!.text_provenance.original.turn_ids.includes(turn.id),
          );
        if (kind === "missing_basis") delete payload.basis;
        const result = parse(payload);
        parserCode =
          result.status === "rejected"
            ? result.code
            : "simulation_integrity_unavailable";
      }
      s.readFailure = {
        kind,
        parserCode,
        truth_verified: false,
        persistence_authorized: false,
      };
      s.view = null;
      s.reviewed = false;
      s.error = readFailureMessages[kind];
      s.outcome = "read_failed";
      // Existing mock identity is retained privately, never replaced, shown
      // or interpreted as a successful/recovered receipt after a read failure.
    } else if (!s.view || !s.reviewed || s.history) {
      s.outcome = "not_saved";
      s.mockReceipt = null;
    } else if (event.fault === "before_mock_result") {
      s.outcome = "response_unknown";
      s.mockReceipt = null;
    } else {
      s.mockReceipt = "SIMULATED-RESULT-1";
      s.outcome =
        event.fault === "after_mock_result"
          ? "response_unknown"
          : "mock_recovered";
    }
  }
  if (event.type === "recover")
    s.outcome = s.mockReceipt ? "mock_recovered" : "not_saved";
  s.actions.push(event.type);
  return s;
}
export function contributionPreview(s: Journey): boolean {
  return (
    !!s.view &&
    !s.readFailure &&
    s.reviewed &&
    !s.history &&
    s.kind === "personal_action" &&
    s.stage === "completed"
  );
}
export function riskReason(s: Journey): string {
  if (!s.history) return "未载入拒绝历史；这不能证明语义独立。";
  const related = [
    "我测试了三个导出按钮。",
    "我验证了3个导出按钮。",
    "我测试了3个导出按钮。",
  ].includes(s.raw);
  return related
    ? "可能只是数字写法或同义表述变化，尚未证明是独立贡献。"
    : "即使看似无关，当前最保守研究政策仍因曾 rejected 的历史阻断；这是可用性代价，尚未证明独立。";
}
