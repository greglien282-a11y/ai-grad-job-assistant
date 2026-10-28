import { defineConfig } from '@playwright/test'
const channel = process.env.PATHWISE_PROTOTYPE_CHANNEL
if (channel && (process.env.CI || !['chrome', 'msedge'].includes(channel))) throw new Error('Explicit local Chromium channel only')
export default defineConfig({
  testDir: '.', workers: 1, retries: 0, timeout: 30000, reporter: 'list', outputDir: '../test-results/resume-lab',
  use: { browserName: 'chromium', channel, trace: 'off', video: 'off' },
  projects: [
    { name: 'local-development', testMatch: /.*\.spec\.ts/, testIgnore: 'production.spec.ts', use: { baseURL: 'http://127.0.0.1:15191' } },
    { name: 'production-closed', testMatch: 'production.spec.ts', use: { baseURL: 'http://127.0.0.1:15192' } },
  ],
  webServer: [
    { command: 'npm run dev -- --force --host 127.0.0.1 --port 15191 --strictPort', url: 'http://127.0.0.1:15191', reuseExistingServer: false, env: { VITE_PATHWISE_JD_LAB: 'synthetic-v1', VITE_PATHWISE_AI_SUGGESTIONS: 'offline-v1' } },
    { command: 'npm run preview -- --host 127.0.0.1 --port 15192 --strictPort', url: 'http://127.0.0.1:15192', reuseExistingServer: false, env: { VITE_PATHWISE_JD_LAB: 'synthetic-v1', VITE_PATHWISE_AI_SUGGESTIONS: 'offline-v1' } },
  ],
})
