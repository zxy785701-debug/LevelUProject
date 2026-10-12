import { defineConfig } from 'vitest/config'
export default defineConfig({
  define: { API_BASE: JSON.stringify('http://127.0.0.1:8000'), MINI_CODE_URL: JSON.stringify('') },
  test: { include: ['tests/**/*.test.ts'], environment: 'node' },
})
