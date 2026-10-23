import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
  test: {
    // Current tests are pure logic. Component tests that need a DOM should
    // opt in per file with `// @vitest-environment jsdom`.
    environment: 'node',
    passWithNoTests: true,
  },
})
