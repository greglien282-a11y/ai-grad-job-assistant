import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import { env } from 'node:process'

const e2e = env.PATHWISE_E2E === '1'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: e2e ? 15173 : 5173,
    strictPort: e2e,
    proxy: {
      '/api': {
        target: e2e ? 'http://127.0.0.1:18000' : 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
  },
})
