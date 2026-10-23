import { describe, expect, it } from "vitest";
import {
  candidate,
  contributionPreview,
  initial,
  transition,
  historyFixture,
  type Kind,
} from "./journey";
import samples from "./scenarios.json";

function prepared(
  text = samples[0].text,
  kind: Kind = "personal_action",
  stage = "completed",
  history = false,
) {
  let s = transition(initial(history ? historyFixture : null), {
    type: "raw",
    value: text,
  });
  s = transition(s, { type: "kind", value: kind });
  s = transition(s, { type: "stage", value: stage });
  return transition(s, { type: "prepare" });
}
describe("explicit type/stage and review stay independent", () => {
  for (const sample of samples)
    it(sample.id, () => {
      const s = prepared(sample.text, sample.kind as Kind, sample.stage);
      expect(s.view).not.toBeNull();
      expect(s.view?.subject.status).toBe("pending");
      expect(s.reviewed).toBe(false);
      expect(contributionPreview(s)).toBe(false);
      const reviewed = transition(s, { type: "review" });
      expect(contributionPreview(reviewed)).toBe(
        sample.kind === "personal_action" && sample.stage === "completed",
      );
      expect(s.view?.turns[0].content).toBe(sample.text);
    });
});
it("requires explicit selection and never classifies arbitrary text", () => {
  const raw = transition(initial(), { type: "raw", value: samples[0].text });
  expect(raw.kind).toBe("");
  expect(raw.stage).toBe("");
  expect(transition(raw, { type: "prepare" }).view).toBeNull();
  expect(prepared("我可能部署过服务。").view).toBeNull();
  expect(
    candidate("我计划部署服务。", "personal_action", "completed"),
  ).toBeNull();
  expect(
    candidate("我正在部署服务。", "personal_action", "completed"),
  ).toBeNull();
  expect(
    candidate("我们部署了服务。", "personal_action", "completed"),
  ).toBeNull();
});
it("keeps original/current/choice sources distinct with code point offsets", () => {
  const raw = "我制作了👩‍💻原型图。";
  const s = prepared(raw);
  expect(s.view?.text_provenance.current.citations[0].end).toBe(
    Array.from(raw).length,
  );
  expect(Array.from(raw).length).toBeLessThan(raw.length);
  const d = s.view?.basis.declaration;
  expect(d?.declaration_source.turn_id).not.toBe(
    s.view?.text_provenance.original.turn_ids[0],
  );
});
it("does not mutate prior state or retain stale confirmed preview", () => {
  const s = transition(prepared(), { type: "review" });
  const before = structuredClone(s);
  const changed = transition(s, { type: "raw", value: "我计划部署服务。" });
  expect(s).toEqual(before);
  expect(changed.reviewed).toBe(false);
  expect(changed.view).toBeNull();
  expect(contributionPreview(changed)).toBe(false);
});
it("explanations retain full rejection history and never unlock", () => {
  let s = transition(
    prepared(samples[0].text, "personal_action", "completed", true),
    { type: "review" },
  );
  const original = structuredClone(s.history);
  for (let i = 1; i <= 3; i++)
    s = transition(s, {
      type: "explain",
      text: `解释${i}`,
      evidence: "未核实资料",
      revision: i,
    });
  expect(s.explanations).toHaveLength(3);
  expect(s.history).toEqual(original);
  expect(contributionPreview(s)).toBe(false);
  s = transition(s, { type: "attempt", fault: "after_mock_result" });
  expect(s.outcome).toBe("not_saved");
  expect(s.mockReceipt).toBeNull();
  s = transition(s, { type: "recover" });
  expect(s.outcome).toBe("not_saved");
  expect(
    transition(s, { type: "raw", value: "我部署了服务。" }).history,
  ).toEqual(original);
});
it("rejects stale explanation and preserves previous explanation rounds", () => {
  const s = prepared(samples[0].text, "personal_action", "completed", true);
  const stale = transition(s, {
    type: "explain",
    text: "解释",
    evidence: "资料",
    revision: 99,
  });
  expect(stale.explanations).toEqual([]);
  expect(stale.error).toContain("版本");
  for (const text of ["\0", "\ud800", "x".repeat(2001)]) {
    expect(
      transition(s, { type: "explain", text, evidence: "资料", revision: 1 })
        .explanations,
    ).toEqual([]);
  }
});
it("separates mock pre-result loss and post-result recovery without replay", () => {
  const s = transition(prepared(), { type: "review" });
  for (const fault of ["before_mock_result", "after_mock_result"] as const) {
    const lost = transition(s, { type: "attempt", fault });
    expect(lost.outcome).toBe("response_unknown");
    const recovered = transition(lost, { type: "recover" });
    expect(recovered.outcome).toBe(
      fault === "after_mock_result" ? "mock_recovered" : "not_saved",
    );
    expect(transition(recovered, { type: "recover" }).mockReceipt).toBe(
      recovered.mockReceipt,
    );
    expect(recovered.actions.filter((x) => x === "attempt")).toHaveLength(1);
  }
});
