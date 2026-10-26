import { test as base, expect, type Page } from "@playwright/test";
import { spawn } from "node:child_process";
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";

const test = base.extend<{
  demo: {
    url: string;
    evidence: () => Promise<{
      evidence: string;
      facts: number;
      permits: number;
    }>;
  };
}>({
  demo: async ({}, use) => {
    const repo = fileURLToPath(new URL("../../../../", import.meta.url));
    const py = process.env.G4_DEMO_PYTHON || "python";
    const child = spawn(
      py,
      [
        "-B",
        "-m",
        "research.g4_disposable_demo.server",
        "--synthetic-disposable",
        "--port",
        "0",
      ],
      { cwd: repo, env: process.env, stdio: ["pipe", "pipe", "pipe"] },
    );
    const lines = createInterface({ input: child.stdout });
    let pending: ((v: Record<string, unknown>) => void) | undefined;
    const queued: Record<string, unknown>[] = [];
    lines.on("line", (line) => {
      const value = JSON.parse(line);
      if (pending) {
        const cb = pending;
        pending = undefined;
        cb(value);
      } else queued.push(value);
    });
    function next(): Promise<Record<string, unknown>> {
      return queued.length
        ? Promise.resolve(queued.shift()!)
        : new Promise((resolve) => {
            pending = resolve;
          });
    }
    const exit = new Promise<void>((resolve, reject) => {
      child.on("exit", (code) =>
        code === 0 ? resolve() : reject(Error("isolated_demo_process_failed")),
      );
      child.on("error", reject);
    });
    // Do not print stderr: fixed failures only; no SQL/body/key in test logs.
    child.stderr.resume();
    try {
      const ready = await Promise.race([
        next(),
        exit.then(() => {
          throw Error("demo_not_ready");
        }),
      ]);
      if (
        typeof ready.ready !== "string" ||
        !ready.ready.startsWith("http://127.0.0.1:")
      )
        throw Error("unsafe_demo_origin");
      await use({
        url: ready.ready,
        evidence: async () => {
          child.stdin.write("EVIDENCE\n");
          return (await next()) as {
            evidence: string;
            facts: number;
            permits: number;
          };
        },
      });
    } finally {
      child.stdin.write("STOP\n");
      await exit;
      lines.close();
      child.stdin.end();
    }
  },
});

async function declare(page: Page) {
  await page.getByLabel("事实类型").selectOption("personal_action");
  await page.getByLabel("进度").selectOption("completed");
}

test("real database commit, event and unicode provenance; GET is zero effect", async ({
  page,
  demo,
}) => {
  const requests: string[] = [];
  page.on("request", (r) => {
    if (r.method() === "POST") requests.push(new URL(r.url()).pathname);
  });
  await page.goto(demo.url);
  await expect(
    page.getByRole("button", { name: "校验并保存到一次性数据库" }),
  ).toBeDisabled();
  await expect(page.getByText("没有可安全展示的已提交结果。")).toBeVisible();
  expect((await demo.evidence()).facts).toBe(0);
  expect(requests).toEqual([]);
  await page.getByLabel("合成样例").selectOption("我制作了👩‍💻原型图。");
  await page.getByLabel("事实类型").selectOption("personal_action");
  await expect(
    page.getByRole("button", { name: "校验并保存到一次性数据库" }),
  ).toBeDisabled();
  expect((await demo.evidence()).facts).toBe(0);
  await page.getByLabel("进度").selectOption("completed");
  await page.getByRole("button", { name: "校验并保存到一次性数据库" }).click();
  await expect(page.getByRole("status")).toContainText(
    "已提交到一次性 PostgreSQL",
  );
  await expect(page.getByRole("article")).toContainText(
    "pending · 用户声明 · 未核实",
  );
  await expect(page.getByRole("article")).toContainText("我制作了👩‍💻原型图。");
  const saved = await demo.evidence();
  expect(saved.facts).toBe(1);
  expect(saved.permits).toBe(1);
  await page.getByRole("button", { name: "只读恢复结果" }).click();
  await expect(page.getByRole("status")).toContainText("只读恢复");
  expect(await demo.evidence()).toEqual(saved);
  expect(requests).toEqual(["/candidate"]);
});

test("actual lost HTTP response uses GET-only recovery without second write", async ({
  page,
  demo,
}) => {
  const posts: string[] = [];
  page.on("request", (r) => {
    if (r.method() === "POST") posts.push(r.url());
  });
  await page.goto(demo.url);
  await declare(page);
  await page.getByLabel("模拟提交成功后响应丢失").check();
  await page.getByRole("button", { name: "校验并保存到一次性数据库" }).click();
  await expect(page.getByRole("status")).toContainText("响应丢失");
  await expect(
    page.getByRole("button", { name: "校验并保存到一次性数据库" }),
  ).toBeDisabled();
  const saved = await demo.evidence();
  expect(saved.facts).toBe(1);
  await page.getByRole("button", { name: "只读恢复结果" }).click();
  await expect(page.getByRole("status")).toContainText("已从一次性 PostgreSQL");
  expect(await demo.evidence()).toEqual(saved);
  expect(posts).toHaveLength(1);
});

test("plan cannot be submitted as completed; explicit plan stays pending", async ({
  page,
  demo,
}) => {
  await page.goto(demo.url);
  await declare(page);
  const before = await demo.evidence();
  await page.getByLabel("合成样例").selectOption("我计划部署服务。");
  await declare(page);
  await page.getByRole("button", { name: "校验并保存到一次性数据库" }).click();
  await expect(page.getByRole("status")).toContainText("本次未保存");
  expect(await demo.evidence()).toEqual(before);
  await page.getByLabel("事实类型").selectOption("plan");
  await page.getByLabel("进度").selectOption("planned");
  await page.getByRole("button", { name: "校验并保存到一次性数据库" }).click();
  await expect(page.getByRole("article")).toContainText("plan / planned");
  await expect(page.getByRole("article")).toContainText("pending");
});

test("unknown read contract clears content and offers no legacy fallback", async ({
  page,
  demo,
}) => {
  await page.goto(demo.url);
  await declare(page);
  await page.getByRole("button", { name: "校验并保存到一次性数据库" }).click();
  await expect(page.getByRole("article")).toBeVisible();
  const saved = await demo.evidence();
  await page.route("**/recover", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ demo_contract: "unknown" }),
    }),
  );
  await page.getByRole("button", { name: "只读恢复结果" }).click();
  await expect(page.getByRole("article")).toHaveCount(0);
  await expect(page.getByRole("status")).toContainText("读取合同不可用");
  expect(await demo.evidence()).toEqual(saved);
});

test("offline GET remains unresolved and creates nothing", async ({
  page,
  context,
  demo,
}) => {
  await page.goto(demo.url);
  await declare(page);
  await page.getByLabel("模拟提交成功后响应丢失").check();
  await page.getByRole("button", { name: "校验并保存到一次性数据库" }).click();
  await expect(page.getByRole("status")).toContainText("响应丢失");
  const saved = await demo.evidence();
  await context.setOffline(true);
  await page.getByRole("button", { name: "只读恢复结果" }).click();
  await expect(page.getByRole("status")).toContainText("网络或读取合同不可用");
  expect(await demo.evidence()).toEqual(saved);
  await context.setOffline(false);
});

test("missing current provenance refuses the whole read, not partial display", async ({
  page,
  demo,
}) => {
  await page.goto(demo.url);
  await declare(page);
  await page.getByRole("button", { name: "校验并保存到一次性数据库" }).click();
  await expect(page.getByRole("article")).toBeVisible();
  const saved = await demo.evidence();
  await page.route("**/recover", async (route) => {
    const r = await route.fetch();
    const value = await r.json();
    value.facts[0].text_provenance.current = [];
    await route.fulfill({ response: r, json: value });
  });
  await page.getByRole("button", { name: "只读恢复结果" }).click();
  await expect(page.getByRole("article")).toHaveCount(0);
  await expect(page.getByRole("status")).toContainText("读取合同不可用");
  expect(await demo.evidence()).toEqual(saved);
});

test("simulated service503 is labelled not saved without a database effect", async ({
  page,
  demo,
}) => {
  await page.goto(demo.url);
  await declare(page);
  const before = await demo.evidence();
  await page.route("**/candidate", (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({ code: "demo_not_saved" }),
    }),
  );
  await page.getByRole("button", { name: "校验并保存到一次性数据库" }).click();
  await expect(page.getByRole("status")).toContainText(
    "独立校验服务不可用，本次未保存",
  );
  await expect(page.getByRole("article")).toHaveCount(0);
  expect(await demo.evidence()).toEqual(before);
});
