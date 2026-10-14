import { defineConfig } from '@playwright/test'

if (process.env.PATHWISE_E2E !== '1' || !process.env.PATHWISE_E2E_RUN_FILE) {
  throw new Error('Use npm run test:e2e: validated isolated environment required')
}
const channel = process.env.PATHWISE_E2E_CHANNEL
if (channel && (channel !== 'msedge' || process.platform !== 'win32' || process.env.CI)) {
  throw new Error('Only explicit local Windows Edge is allowed; CI always uses bundled Chromium')
}
export default defineConfig({
  testDir: './e2e', testMatch: '**/*.spec.ts', fullyParallel: false, workers: 1, retries: 0,
  timeout: 30000, reporter: [['list'], ['html', { open: 'never' }]],
  use: { baseURL: 'http://127.0.0.1:15173', browserName: 'chromium', channel,
    trace: 'off', video: 'off', screenshot: 'off' },
})
