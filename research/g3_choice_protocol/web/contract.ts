/** Separate A event candidate. Structural checks do NOT authenticate a DTO. */
import type {
  Classification,
  Subject,
  Citation,
} from "../../declaration_read/web/contract";
export const READ_CONTRACT = "g3-choice-basis-read-candidate-v1";
export const EVENT_CONTRACT = "g3-choice-event-ref-v1";
export const SCOPE = "synthetic_or_disposable_reference_only";
export type Turn = {
  source_kind: "conversation_turn";
  id: string;
  session_id: string;
  project_id: string;
  role: "user";
  content: string;
};
export type AuthContext = {
  id: string;
  source_kind: "server_authenticated_session";
  session_id: string;
  project_id: string;
  operation_id: string;
  authenticated_subject: string;
  issuer: "synthetic-server-auth-v1";
  db_login: string;
  recorded_at: string;
};
export type ChoiceEvent = {
  event_contract: typeof EVENT_CONTRACT;
  source_kind: "immutable_user_choice_event";
  id: string;
  session_id: string;
  project_id: string;
  fact_id: string;
  fact_version: number;
  operation_id: string;
  effect_slot: number;
  change_id: string;
  classification: Classification;
  statement_citations: Citation[];
  selection: {
    id: string;
    source_kind: "explicit_ui_selection";
    classification: Classification;
  };
  authentication_context: AuthContext;
  recorded_validation: {
    contract: "typed-semantic-spike-v1";
    status: "eligible_candidate";
    code: "finite_rule_match";
  };
  recorded_at: string;
};
export type Envelope = {
  read_contract: typeof READ_CONTRACT;
  scope: typeof SCOPE;
  subject: Subject;
  turns: Turn[];
  text_provenance: { original: Citation[]; current: Citation[] };
  basis:
    | { status: "legacy_unclassified" | "not_recorded"; event: null }
    | { status: "event_recorded"; event: ChoiceEvent };
};
const flags = {
  evidence_class: "structural_read_candidate_only",
  authentication_verified: false,
  database_history_verified: false,
  language_validation_replayed: false,
  truth_verified: false,
  persistence_authorized: false,
} as const;
export type Result<T = Envelope> = typeof flags & {
  status: "parsed_candidate" | "rejected";
  code: string;
  view: T | null;
};
type Dict = Record<string, unknown>;
class Invalid extends Error {}
function need(
  condition: unknown,
  code = "candidate_shape_invalid",
): asserts condition {
  if (!condition) throw new Invalid(code);
}
function obj(v: unknown, keys: string[]): Dict {
  need(v !== null && typeof v === "object" && !Array.isArray(v));
  need(
    Object.keys(v).length === keys.length &&
      keys.every((k) => Object.hasOwn(v, k)),
  );
  return v as Dict;
}
function arr(v: unknown, min = 0, max = 5): unknown[] {
  need(Array.isArray(v) && v.length >= min && v.length <= max);
  return v;
}
function str(v: unknown, max = 10000): string {
  need(
    typeof v === "string" &&
      [...v].length > 0 &&
      [...v].length <= max &&
      !v.includes("\0"),
  );
  for (const cp of v)
    need(
      cp.length !== 1 || cp.charCodeAt(0) < 0xd800 || cp.charCodeAt(0) > 0xdfff,
      "candidate_text_invalid",
    );
  return v;
}
function id(v: unknown): string {
  need(typeof v === "string");
  need(
    v.length === 36 &&
      /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(v),
    "candidate_identifier_invalid",
  );
  return v;
}
function integer(v: unknown, min = 1): number {
  need(typeof v === "number" && Number.isSafeInteger(v) && v >= min);
  return v;
}
const labelKeys = ["fact_kind", "progress_stage", "classification_contract"];
function labels(v: Dict) {
  const k = v.fact_kind,
    p = v.progress_stage,
    c = v.classification_contract;
  const stages: Record<string, string[]> = {
    personal_action: ["completed", "in_progress"],
    plan: ["planned", "in_progress"],
    background: ["not_applicable"],
    boundary: ["not_applicable"],
  };
  need(
    typeof k === "string" &&
      typeof p === "string" &&
      typeof c === "string" &&
      (k === "legacy_unspecified"
        ? p === "legacy_unknown" && ["legacy-v0", "unclassified-v1"].includes(c)
        : c === "explicit-typed-v1" &&
          Object.hasOwn(stages, k) &&
          stages[k].includes(p)),
    "candidate_classification_invalid",
  );
}
function same(a: unknown, b: unknown): boolean {
  if (Array.isArray(a) && Array.isArray(b))
    return a.length === b.length && a.every((v, i) => same(v, b[i]));
  if (
    a !== null &&
    b !== null &&
    typeof a === "object" &&
    typeof b === "object"
  ) {
    const x = a as Dict,
      y = b as Dict;
    return (
      Object.keys(x).length === Object.keys(y).length &&
      Object.keys(x).every((k) => Object.hasOwn(y, k) && same(x[k], y[k]))
    );
  }
  return a === b;
}
function stamp(v: unknown): string {
  need(
    typeof v === "string" &&
      v.endsWith("Z") &&
      /^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?Z$/.test(
        v,
      ),
    "candidate_timestamp_invalid",
  );
  const base = v.slice(0, 19),
    n = Date.parse(base + "Z");
  need(
    !base.startsWith("0000-") &&
      Number.isFinite(n) &&
      new Date(n).toISOString().slice(0, 19) === base,
    "candidate_timestamp_invalid",
  );
  return (
    base + "." + (v.includes(".") ? v.slice(20, -1) : "").padEnd(6, "0") + "Z"
  );
}
function cites(value: unknown, turns: Map<string, Turn>): Set<string> {
  const keys = new Set<string>(),
    ends = new Map<string, number>();
  for (const valueItem of arr(value)) {
    const c = obj(valueItem, ["turn_id", "start", "end", "quote"]),
      tid = id(c.turn_id);
    const start = integer(c.start, 0),
      end = integer(c.end),
      quote = str(c.quote, 500),
      turn = turns.get(tid);
    need(turn?.role === "user", "candidate_source_invalid");
    const text = [...turn.content];
    need(
      start < end &&
        end <= text.length &&
        text.slice(start, end).join("") === quote,
      "candidate_quote_mismatch",
    );
    const key = `${tid}:${start}:${end}`;
    need(!keys.has(key), "candidate_duplicate_source");
    need(start >= (ends.get(tid) ?? 0), "candidate_source_order_invalid");
    keys.add(key);
    ends.set(tid, end);
  }
  return keys;
}
function setSame(a: Set<string>, b: Set<string>) {
  return a.size === b.size && [...a].every((k) => b.has(k));
}
function checked(payload: unknown): Envelope {
  const root = obj(payload, [
    "read_contract",
    "scope",
    "subject",
    "turns",
    "text_provenance",
    "basis",
  ]);
  need(root.read_contract === READ_CONTRACT, "candidate_version_unsupported");
  need(root.scope === SCOPE, "candidate_scope_required");
  const s = obj(root.subject, [
    ...labelKeys,
    "fact_id",
    "session_id",
    "project_id",
    "fact_version",
    "statement",
    "status",
  ]);
  labels(s);
  for (const k of ["fact_id", "session_id", "project_id"]) id(s[k]);
  integer(s.fact_version);
  str(s.statement, 500);
  need(
    typeof s.status === "string" &&
      ["pending", "user_confirmed", "evidence_supported", "rejected"].includes(
        s.status,
      ),
  );
  const turns = new Map<string, Turn>();
  for (const raw of arr(root.turns, 1, 10)) {
    const t = obj(raw, [
      "source_kind",
      "id",
      "session_id",
      "project_id",
      "role",
      "content",
    ]);
    const tid = id(t.id);
    id(t.session_id);
    id(t.project_id);
    str(t.content);
    need(
      t.source_kind === "conversation_turn" && t.role === "user",
      "candidate_source_invalid",
    );
    need(
      t.session_id === s.session_id && t.project_id === s.project_id,
      "candidate_session_mismatch",
    );
    need(!turns.has(tid), "candidate_duplicate_source");
    turns.set(tid, t as Turn);
  }
  const provenance = obj(root.text_provenance, ["original", "current"]),
    original = cites(provenance.original, turns),
    current = cites(provenance.current, turns);
  need(original.size > 0 && current.size > 0, "candidate_source_invalid");
  need(
    (provenance.current as Citation[]).every((c) => c.quote === s.statement),
    "candidate_statement_mismatch",
  );
  need(
    setSame(
      new Set(turns.keys()),
      new Set([...original, ...current].map((k) => k.slice(0, 36))),
    ),
    "candidate_unreferenced_source",
  );
  const basis = obj(root.basis, ["status", "event"]);
  if (
    basis.status === "legacy_unclassified" ||
    basis.status === "not_recorded"
  ) {
    need(
      basis.status ===
        (s.classification_contract === "legacy-v0"
          ? "legacy_unclassified"
          : "not_recorded") && basis.event === null,
      "candidate_basis_status_mismatch",
    );
    return root as Envelope;
  }
  need(
    basis.status === "event_recorded" &&
      s.classification_contract === "explicit-typed-v1",
    "candidate_basis_status_mismatch",
  );
  const e = obj(basis.event, [
    "event_contract",
    "source_kind",
    "id",
    "session_id",
    "project_id",
    "fact_id",
    "fact_version",
    "operation_id",
    "effect_slot",
    "change_id",
    "classification",
    "statement_citations",
    "selection",
    "authentication_context",
    "recorded_validation",
    "recorded_at",
  ]);
  need(
    e.event_contract === EVENT_CONTRACT,
    "candidate_event_version_unsupported",
  );
  need(
    e.source_kind === "immutable_user_choice_event",
    "candidate_event_source_invalid",
  );
  for (const k of [
    "id",
    "session_id",
    "project_id",
    "fact_id",
    "operation_id",
    "change_id",
  ])
    id(e[k]);
  integer(e.fact_version);
  need(
    ["session_id", "project_id", "fact_id", "fact_version"].every(
      (k) => e[k] === s[k],
    ),
    "candidate_event_subject_mismatch",
  );
  need(integer(e.effect_slot) <= 5);
  const classification = obj(e.classification, labelKeys);
  labels(classification);
  need(
    labelKeys.every((k) => classification[k] === s[k]),
    "candidate_event_classification_mismatch",
  );
  need(
    setSame(cites(e.statement_citations, turns), current),
    "candidate_event_source_mismatch",
  );
  const selection = obj(e.selection, ["id", "source_kind", "classification"]);
  id(selection.id);
  need(
    selection.source_kind === "explicit_ui_selection",
    "candidate_choice_source_invalid",
  );
  obj(selection.classification, labelKeys);
  need(
    same(selection.classification, classification),
    "candidate_choice_mismatch",
  );
  const auth = obj(e.authentication_context, [
    "id",
    "source_kind",
    "session_id",
    "project_id",
    "operation_id",
    "authenticated_subject",
    "issuer",
    "db_login",
    "recorded_at",
  ]);
  for (const k of [
    "id",
    "session_id",
    "project_id",
    "operation_id",
    "authenticated_subject",
  ])
    id(auth[k]);
  need(
    auth.source_kind === "server_authenticated_session" &&
      auth.issuer === "synthetic-server-auth-v1",
    "candidate_auth_context_invalid",
  );
  need(
    ["session_id", "project_id", "operation_id"].every((k) => auth[k] === e[k]),
    "candidate_auth_context_mismatch",
  );
  str(auth.db_login, 63);
  need(
    stamp(auth.recorded_at) <= stamp(e.recorded_at),
    "candidate_timestamp_invalid",
  );
  const validation = obj(e.recorded_validation, ["contract", "status", "code"]);
  need(
    same(validation, {
      contract: "typed-semantic-spike-v1",
      status: "eligible_candidate",
      code: "finite_rule_match",
    }),
    "candidate_validation_record_unsupported",
  );
  return root as Envelope;
}
function reject<T>(e: unknown): Result<T> {
  return {
    status: "rejected",
    code: e instanceof Invalid ? e.message : "candidate_shape_invalid",
    view: null,
    ...flags,
  };
}
export function parse(payload: unknown): Result {
  try {
    return {
      status: "parsed_candidate",
      code: "candidate_internally_consistent",
      view: structuredClone(checked(payload)),
      ...flags,
    };
  } catch (e) {
    return reject(e);
  }
}
export function parseBatch(payloads: unknown): Result<Envelope[]> {
  try {
    const views = arr(payloads, 1).map(checked);
    need(
      views.every((v) => v.basis.status === "event_recorded"),
      "candidate_batch_basis_required",
    );
    const events = views.map((v) => v.basis.event as ChoiceEvent),
      first = events[0];
    need(
      events.every((e, i) => e.effect_slot === i + 1),
      "candidate_batch_slots_invalid",
    );
    for (const k of ["id", "fact_id", "change_id"] as const)
      need(
        new Set(events.map((e) => e[k])).size === events.length,
        "candidate_batch_reused_event",
      );
    need(
      new Set(events.map((e) => e.selection.id)).size === events.length,
      "candidate_batch_reused_event",
    );
    need(
      events.every((e) =>
        [
          "session_id",
          "project_id",
          "operation_id",
          "authentication_context",
        ].every((k) =>
          same(e[k as keyof ChoiceEvent], first[k as keyof ChoiceEvent]),
        ),
      ),
      "candidate_batch_operation_mismatch",
    );
    need(
      events.every((e) => e.statement_citations.length === 1),
      "candidate_batch_sources_invalid",
    );
    const knownTurns = new Map<string, Turn>();
    for (const v of views)
      for (const t of v.turns) {
        need(
          !knownTurns.has(t.id) || same(knownTurns.get(t.id), t),
          "candidate_batch_sources_invalid",
        );
        knownTurns.set(t.id, t);
      }
    const tid = events[0].statement_citations[0].turn_id;
    let previous = 0;
    for (const e of events) {
      const c = e.statement_citations[0];
      need(
        c.turn_id === tid && c.start >= previous,
        "candidate_batch_sources_invalid",
      );
      previous = c.end;
    }
    const strip = (s: string) => s.replace(/[ \t\r\n]/g, "");
    need(
      strip(knownTurns.get(tid)!.content) ===
        strip(events.map((e) => e.statement_citations[0].quote).join("")),
      "candidate_batch_sources_invalid",
    );
    return {
      status: "parsed_candidate",
      code: "candidate_batch_internally_consistent",
      view: structuredClone(views),
      ...flags,
    };
  } catch (e) {
    return reject(e);
  }
}
export function basisLabel(view: Envelope): string {
  return view.basis.status === "legacy_unclassified"
    ? "旧资料未分类，未推断完成情况"
    : view.basis.status === "not_recorded"
      ? "暂无分类依据记录"
      : "已记录用户分类选择；不代表平台独立认证";
}

export function parseJson(input: unknown): Result {
  try {
    need(typeof input === "string" && Array.from(input).length <= 150000);
    const text = input;
    let pos = 0;
    function space() {
      while (/^[ \r\n\t]$/.test(text[pos] ?? "")) pos++;
    }
    function quoted(): string {
      const start = pos++;
      while (pos < text.length) {
        const ch = text[pos++];
        if (ch === "\\") {
          pos++;
          continue;
        }
        if (ch === '"') return JSON.parse(text.slice(start, pos)) as string;
      }
      throw new Invalid("candidate_json_invalid");
    }
    function value(depth: number): void {
      need(depth < 100, "candidate_json_invalid");
      space();
      const ch = text[pos];
      if (ch === '"') {
        quoted();
        return;
      }
      if (ch === "{") {
        pos++;
        space();
        const seen = new Set<string>();
        if (text[pos] === "}") {
          pos++;
          return;
        }
        while (true) {
          space();
          need(text[pos] === '"', "candidate_json_invalid");
          const key = quoted();
          need(!seen.has(key), "candidate_duplicate_key");
          seen.add(key);
          space();
          need(text[pos++] === ":", "candidate_json_invalid");
          value(depth + 1);
          space();
          if (text[pos] === "}") {
            pos++;
            return;
          }
          need(text[pos++] === ",", "candidate_json_invalid");
        }
      }
      if (ch === "[") {
        pos++;
        space();
        if (text[pos] === "]") {
          pos++;
          return;
        }
        while (true) {
          value(depth + 1);
          space();
          if (text[pos] === "]") {
            pos++;
            return;
          }
          need(text[pos++] === ",", "candidate_json_invalid");
        }
      }
      const literal = /^(true|false|null)/.exec(text.slice(pos));
      if (literal) {
        pos += literal[0].length;
        return;
      }
      const number =
        /^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?/.exec(
          text.slice(pos),
        );
      need(number, "candidate_json_invalid");
      need(
        !/[.eE]/.test(number[0]) && Number.isSafeInteger(Number(number[0])),
        "candidate_shape_invalid",
      );
      pos += number[0].length;
    }
    value(0);
    space();
    need(pos === text.length, "candidate_json_invalid");
    return parse(JSON.parse(text));
  } catch (e) {
    return {
      status: "rejected",
      code: e instanceof Invalid ? e.message : "candidate_json_invalid",
      view: null,
      ...flags,
    };
  }
}
