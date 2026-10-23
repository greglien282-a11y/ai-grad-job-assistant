import { test, expect, type Page } from "@playwright/test";
async function select(page: Page, sample: string, kind: string, stage: string) {
  await page.getByRole("button", { name: sample, exact: true }).click();
  await expect(page.getByLabel("事实类型")).toHaveValue("");
  await page.getByLabel("事实类型").selectOption(kind);
  await page.getByLabel("进度阶段").selectOption(stage);
  await page.getByRole("button", { name: "查看候选与来源" }).click();
}
test("complete synthetic journey, distinct sources and recovery make no API requests", async ({
  page,
}) => {
  const requests: { method: string; url: string }[] = [];
  page.on("request", (r) =>
    requests.push({ method: r.method(), url: r.url() }),
  );
  await page.goto("/");
  await expect(page.getByText("合成演示 · 未保存")).toBeVisible();
  await select(page, "整理记录", "personal_action", "completed");
  await expect(page.getByRole("blockquote")).toHaveText(
    "我整理了27条缺失记录。",
  );
  await expect(
    page.getByText("独立分类选择来源 / synthetic Turn 6"),
  ).toBeVisible();
  await expect(page.getByTestId("review-status")).toContainText("待审核");
  await page.getByRole("button", { name: "模拟用户审核（不保存）" }).click();
  await expect(page.getByTestId("qualification")).toContainText(
    "模拟正文预览资格",
  );
  await page.getByLabel("模拟故障点").selectOption("after_mock_result");
  await page.getByRole("button", { name: "模拟操作结果（不保存）" }).click();
  await expect(page.getByRole("status")).toContainText("模拟响应未知");
  await page.getByRole("button", { name: "只查看内存恢复结果" }).click();
  await expect(page.getByRole("status")).toContainText("不是持久回执");
  await page.screenshot({
    path: "test-results/evidence/journey-desktop.png",
    fullPage: true,
  });
  await page.getByText("查看本次内存操作记录", { exact: true }).click();
  await expect(
    page
      .locator("details")
      .filter({ hasText: "查看本次内存操作记录" })
      .getByRole("listitem")
      .filter({ hasText: /^attempt$/ }),
  ).toHaveCount(1);
  expect(requests.every((r) => r.method === "GET")).toBe(true);
  expect(
    requests.some((r) => new URL(r.url).pathname.startsWith("/api/")),
  ).toBe(false);
  await page.reload();
  await expect(page.getByLabel("经历原话")).toHaveValue("");
  await expect(page.getByRole("status")).toHaveText("尚无模拟操作。");
});
for (const c of [
  ["未来计划", "plan", "planned"],
  ["进行中", "personal_action", "in_progress"],
  ["团队背景", "background", "not_applicable"],
  ["个人限制", "boundary", "not_applicable"],
]) {
  test(`${c[0]} never becomes a completed personal contribution`, async ({
    page,
  }) => {
    await page.goto("/");
    await select(page, c[0], c[1], c[2]);
    await page.getByRole("button", { name: "模拟用户审核（不保存）" }).click();
    await expect(page.getByTestId("qualification")).toContainText(
      "不进入已完成个人贡献正文",
    );
  });
}
test("R03 history and explanation stay blocked, including unrelated contribution", async ({
  page,
}) => {
  await page.goto("/");
  await select(page, "数字写法变化", "personal_action", "completed");
  await expect(
    page.getByText("原始拒绝表述：「我测试了3个导出按钮。」"),
  ).toBeVisible();
  await expect(
    page.getByText("可能只是数字写法或同义表述变化，尚未证明是独立贡献。"),
  ).toBeVisible();
  await page.getByLabel("补充解释").fill("这是另一次检查，但独立性尚待审核。");
  await page
    .getByLabel("额外证据描述（未核实，不访问链接）")
    .fill("合成日志；没有认证。");
  await page
    .getByRole("button", { name: "追加解释，继续等待独立审核" })
    .click();
  await expect(page.getByRole("list", { name: "解释记录" })).toContainText(
    "这是另一次检查",
  );
  await page.getByRole("button", { name: "模拟用户审核（不保存）" }).click();
  await page.getByRole("button", { name: "模拟操作结果（不保存）" }).click();
  await expect(page.getByRole("status")).toContainText("未保存");
  await expect(
    page.getByText("拒绝历史没有被删除。", { exact: false }),
  ).toBeVisible();
  await page.screenshot({
    path: "test-results/evidence/clarification.png",
    fullPage: true,
  });
  await select(page, "无关贡献被阻断", "personal_action", "completed");
  await expect(page.getByText("即使看似无关", { exact: false })).toBeVisible();
});
test("Unicode quotes remain exact and changed draft clears reviewed preview", async ({
  page,
}) => {
  await page.goto("/");
  await select(page, "Unicode 原话", "personal_action", "completed");
  await expect(page.getByRole("blockquote")).toHaveText("我制作了👩‍💻原型图。");
  await page.getByRole("button", { name: "模拟用户审核（不保存）" }).click();
  await page.getByLabel("经历原话").fill("我计划部署服务。");
  await expect(page.getByTestId("review-status")).toContainText("待审核");
  await expect(
    page.getByRole("button", { name: "模拟操作结果（不保存）" }),
  ).toBeDisabled();
});
test("unsupported forged completed declaration is refused", async ({
  page,
}) => {
  await page.goto("/");
  await select(page, "未来计划", "personal_action", "completed");
  await expect(page.getByRole("alert")).toContainText("需要澄清，未保存");
  await expect(
    page.getByRole("button", { name: "模拟用户审核（不保存）" }),
  ).toBeDisabled();
});
test("narrow screen keeps original/source and controls visible without horizontal scrolling", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await select(page, "Unicode 原话", "personal_action", "completed");
  await expect(page.getByRole("blockquote")).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "test-results/evidence/journey-mobile.png",
    fullPage: true,
  });
});
