import { readFileSync } from "node:fs";
import { describe, it, expect } from "vitest";
import {
  parse,
  parseJson,
  parseBatch,
  basisLabel,
  type Envelope,
  type ChoiceEvent,
} from "./contract";
const corpus = JSON.parse(
  readFileSync(new URL("../read_cases.json", import.meta.url), "utf8"),
) as {
  base: Envelope;
  cases: { name: string; patches: [string[], unknown][]; code: string }[];
};
function patched(patches: [string[], unknown][]): unknown {
  const value = structuredClone(corpus.base);
  for (const [path, item] of patches) {
    let target = value as unknown as Record<string, unknown>;
    for (const key of path.slice(0, -1))
      target = target[key] as Record<string, unknown>;
    target[path.at(-1)!] = structuredClone(item);
  }
  return value;
}
describe("shared strict corpus", () => {
  for (const c of corpus.cases)
    it(c.name, () => {
      const input = patched(c.patches),
        before = structuredClone(input),
        result = parse(input);
      expect(result.code).toBe(c.code);
      expect(result.status).toBe(
        c.code === "candidate_internally_consistent"
          ? "parsed_candidate"
          : "rejected",
      );
      expect(input).toEqual(before);
      expect(result).toMatchObject({
        authentication_verified: false,
        database_history_verified: false,
        language_validation_replayed: false,
        truth_verified: false,
        persistence_authorized: false,
      });
      if (result.status === "rejected") expect(result.view).toBeNull();
    });
});
const pairs = [
  ["legacy_unspecified", "legacy_unknown", "legacy-v0"],
  ["legacy_unspecified", "legacy_unknown", "unclassified-v1"],
  ["personal_action", "completed", "explicit-typed-v1"],
  ["personal_action", "in_progress", "explicit-typed-v1"],
  ["plan", "planned", "explicit-typed-v1"],
  ["plan", "in_progress", "explicit-typed-v1"],
  ["background", "not_applicable", "explicit-typed-v1"],
  ["boundary", "not_applicable", "explicit-typed-v1"],
];
for (const [kind, stage, contract] of pairs)
  for (const status of [
    "pending",
    "user_confirmed",
    "evidence_supported",
    "rejected",
  ]) {
    it(`structural labels ${kind}/${stage}/${contract} are independent from ${status} and truth`, () => {
      const value = structuredClone(corpus.base);
      const labels = {
        fact_kind: kind,
        progress_stage: stage,
        classification_contract: contract,
      } as Envelope["subject"];
      Object.assign(value.subject, labels, { status });
      if (contract === "explicit-typed-v1") {
        const event = value.basis.event!;
        event.classification = structuredClone(labels);
        event.selection.classification = structuredClone(labels);
      } else
        value.basis = {
          status:
            contract === "legacy-v0" ? "legacy_unclassified" : "not_recorded",
          event: null,
        };
      const result = parse(value);
      expect(result.status).toBe("parsed_candidate");
      expect(result.view!.subject.status).toBe(status);
      expect(result.truth_verified).toBe(false);
      expect(result.language_validation_replayed).toBe(false);
      expect(result.view!.subject.statement).toBe(
        corpus.base.subject.statement,
      );
      expect(basisLabel(result.view!)).not.toContain("已经验证");
    });
  }
for (const [text, code] of [
  ['{"read_contract":1,"read_\\u0063ontract":2}', "candidate_duplicate_key"],
  ['{"x":NaN}', "candidate_json_invalid"],
  ['{"x":9007199254740992}', "candidate_shape_invalid"],
  ['{"x":1.0}', "candidate_shape_invalid"],
  ['{"x":1e0}', "candidate_shape_invalid"],
  ['{"x":', "candidate_json_invalid"],
])
  it(`strict raw JSON ${text}`, () => {
    expect(parseJson(text)).toMatchObject({
      status: "rejected",
      code,
      view: null,
    });
  });

const texts = [
  "我部署了服务。",
  "我编写了脚本。",
  "我制作了👩‍💻原型图。",
  "我测试了导出按钮。",
  "我整理了27条缺失记录。",
];
const uuid = (n: number) =>
  `00000000-0000-0000-0000-${n.toString(16).padStart(12, "0")}`;
function batch(n = 3): Envelope[] {
  const raw = texts.slice(0, n).join("\r\n");
  let cursor = 0;
  return texts.slice(0, n).map((quote, i) => {
    const v = structuredClone(corpus.base),
      startUtf16 = raw.indexOf(quote, cursor),
      start = [...raw.slice(0, startUtf16)].length;
    cursor = startUtf16 + quote.length;
    const cite = {
      turn_id: v.turns[0].id,
      start,
      end: start + [...quote].length,
      quote,
    };
    v.turns[0].content = raw;
    v.subject.statement = quote;
    v.subject.fact_id = uuid(100 + i);
    v.text_provenance = { original: [cite], current: [cite] };
    Object.assign(v.basis.event!, {
      id: uuid(200 + i),
      fact_id: v.subject.fact_id,
      change_id: uuid(300 + i),
      effect_slot: i + 1,
      statement_citations: [cite],
    });
    v.basis.event!.selection.id = uuid(400 + i);
    return v;
  });
}
for (const n of [1, 3, 5])
  it(`synthetic batch ${n} is not a database proof`, () => {
    const values = batch(n);
    expect(parseBatch(values)).toMatchObject({
      status: "parsed_candidate",
      database_history_verified: false,
      persistence_authorized: false,
    });
    expect(parseJson(JSON.stringify(values[0])).status).toBe(
      "parsed_candidate",
    );
  });
for (const fault of [
  "event",
  "fact",
  "change",
  "selection",
  "slot",
  "auth",
  "turn_content",
  "source_reuse",
  "missing_body",
]) {
  it(`batch rejects ${fault} without a partial view`, () => {
    const values = batch(),
      a = values[0].basis.event as ChoiceEvent,
      b = values[1].basis.event as ChoiceEvent;
    if (fault === "event") b.id = a.id;
    else if (fault === "change") b.change_id = a.change_id;
    else if (fault === "fact") {
      b.fact_id = a.fact_id;
      values[1].subject.fact_id = a.fact_id;
    } else if (fault === "selection") b.selection.id = a.selection.id;
    else if (fault === "slot") b.effect_slot = a.effect_slot;
    else if (fault === "auth")
      b.authentication_context.authenticated_subject = uuid(999);
    else if (fault === "turn_content") values[1].turns[0].content += "额外文字";
    else if (fault === "missing_body")
      values.forEach((v) => {
        v.turns[0].content += "遗漏限定语";
      });
    else {
      values[1].subject.statement = values[0].subject.statement;
      values[1].text_provenance = structuredClone(values[0].text_provenance);
      b.statement_citations = structuredClone(a.statement_citations);
    }
    expect(parseBatch(values)).toMatchObject({
      status: "rejected",
      view: null,
      persistence_authorized: false,
    });
  });
}

it("does not reinterpret the G2.1 Turn-based contract or a formal FactV3", () => {
  expect(
    parse({ read_contract: "classification-declaration-read-candidate-v1" })
      .status,
  ).toBe("rejected");
  expect(
    parse({ contract_version: 3, classification_citations: [] }).status,
  ).toBe("rejected");
  const input = structuredClone(corpus.base);
  const result = parse(input);
  input.subject.statement = "changed after parsing";
  expect(result.view!.subject.statement).toBe(corpus.base.subject.statement);
});
