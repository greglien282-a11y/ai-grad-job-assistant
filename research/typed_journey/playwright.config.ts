import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./tests",
  retries: 0,
  workers: 1,
  use: {
    baseURL: "http://127.0.0.1:5187",
    browserName: "chromium",
    channel: process.env.PATHWISE_PROTOTYPE_CHANNEL || undefined,
    trace: "retain-on-failure",
  },
  webServer: {
    command: "npm run dev",
    url: "http://127.0.0.1:5187",
    reuseExistingServer: false,
  },
  reporter: [["list"]],
});
