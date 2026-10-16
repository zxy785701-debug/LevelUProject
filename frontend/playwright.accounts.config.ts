import { defineConfig } from '@playwright/test'
export default defineConfig({
  testDir: './e2e-accounts', timeout: 60000,
  use: { baseURL: process.env.LEVELUP_E2E_UI_ORIGIN || 'http://127.0.0.1:10086', viewport: { width: 390, height: 812 }, headless: true, channel: 'chrome' },
  reporter: [['list'], ['html', { outputFolder: '../docs/quiz-grounding/account-playwright-report', open: 'never' }]],
  outputDir: '../docs/quiz-grounding/account-e2e-results', workers: 1,
})
