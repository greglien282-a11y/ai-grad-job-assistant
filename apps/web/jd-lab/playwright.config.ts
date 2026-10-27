import { defineConfig } from '@playwright/test'
const channel = process.env.PATHWISE_PROTOTYPE_CHANNEL
if (channel && (process.env.CI || !['chrome', 'msedge'].includes(channel))) throw new Error('Explicit local Chromium channel only')
export default defineConfig({
  testDir: '.', workers: 1, retries: 0, timeout: 30000,
  reporter: 'list', outputDir: '../test-results/jd-lab',
  use: { browserName: 'chromium', channel, screenshot: 'only-on-failure', trace: 'off', video: 'off' },
  projects: [
    { name: 'enabled-development', testMatch: 'enabled.spec.ts', use: { baseURL: 'http://127.0.0.1:15187' } },
    { name: 'production-closed', testMatch: 'production.spec.ts', use: { baseURL: 'http://127.0.0.1:15188' } },
  ],
  webServer: [
    { command: 'npm run dev -- --host 127.0.0.1 --port 15187 --strictPort', url: 'http://127.0.0.1:15187', reuseExistingServer: false, env: { VITE_PATHWISE_JD_LAB: 'synthetic-v1' } },
    { command: 'npm run preview -- --host 127.0.0.1 --port 15188 --strictPort', url: 'http://127.0.0.1:15188', reuseExistingServer: false, env: { VITE_PATHWISE_JD_LAB: 'synthetic-v1' } },
  ],
})
