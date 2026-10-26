import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./tests",
  retries: 0,
  workers: 1,
  use: {
    browserName: "chromium",
    channel: process.env.PATHWISE_PROTOTYPE_CHANNEL || undefined,
    trace: "retain-on-failure",
  },
  reporter: [["list"]],
});
