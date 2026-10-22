import { defineConfig } from '@playwright/test'
export default defineConfig({
  testDir: './e2e-knowledge-prototype', timeout: 45000, expect: { timeout: 10000 }, workers: 1,
  use: { baseURL: process.env.LEVELUP_E2E_UI_ORIGIN || 'http://127.0.0.1:10086', viewport: { width: 390, height: 812 }, headless: true, channel: 'chrome', trace: 'retain-on-failure' },
  reporter: [['list'], ['html', { outputFolder: '../docs/knowledge-prototype/page-report', open: 'never' }]],
  outputDir: '../docs/knowledge-prototype/page-results',
})
