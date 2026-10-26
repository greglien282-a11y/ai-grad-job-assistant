/** Mandatory explicit evidence path; static JSON cannot stand in for this. */
import { readFileSync } from "node:fs";
import { expect, it } from "vitest";
import { parse, parseBatch, parseJson } from "./contract";
it("strictly consumes the five views actually projected by restricted PostgreSQL", () => {
  const path = process.env.G3_PG_CANDIDATE_FILE;
  expect(
    path,
    "Run the disposable PostgreSQL suite with the same explicit evidence path first",
  ).toBeTruthy();
  const views: unknown = JSON.parse(readFileSync(path!, "utf8"));
  const result = parseBatch(views);
  expect(result.status).toBe("parsed_candidate");
  expect(result.view).toHaveLength(5);
  for (const view of result.view!) {
    expect(parse(view).status).toBe("parsed_candidate");
    expect(parseJson(JSON.stringify(view)).status).toBe("parsed_candidate");
    expect(view.basis.status).toBe("event_recorded");
    expect(view.basis.event!.source_kind).toBe("immutable_user_choice_event");
    expect(view.basis.event!.authentication_context.db_login).toMatch(
      /^g3_writer_/,
    );
    expect(view.subject.status).toBe("pending");
  }
  expect(result.truth_verified).toBe(false);
  expect(result.authentication_verified).toBe(false);
  expect(result.persistence_authorized).toBe(false);
});
