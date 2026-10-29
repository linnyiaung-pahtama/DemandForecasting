import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// Node's `process` is available when Vite loads this file; @types/node is not a dependency.
declare const process: { env: Record<string, string | undefined> }

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': process.env.ORDERPLAN_API ?? 'http://127.0.0.1:8000',
    },
  },
  test: {
    // Current tests are pure logic. Component tests that need a DOM should
    // opt in per file with `// @vitest-environment jsdom`.
    environment: 'node',
    passWithNoTests: true,
  },
})
