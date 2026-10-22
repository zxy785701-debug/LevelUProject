import { defineConfig } from '@playwright/test'
export default defineConfig({
  testDir: './e2e-knowledge', timeout: 90000, expect: { timeout: 20000 },
  use: { baseURL: 'http://127.0.0.1:10086', viewport: { width: 390, height: 812 }, headless: true, channel: 'chrome', trace: 'retain-on-failure' },
  reporter: [['list'], ['html', { outputFolder: '../docs/knowledge-rag/page-report', open: 'never' }]],
  outputDir: '../docs/knowledge-rag/page-results', workers: 1,
})
