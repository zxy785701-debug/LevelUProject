import { defineConfig } from '@playwright/test'
export default defineConfig({
  testDir: './e2e-grounding', timeout: 30000,
  use: { baseURL: 'http://127.0.0.1:10087', viewport: { width: 390, height: 812 }, headless: true, channel: 'chrome' },
  reporter: [['list'], ['html', { outputFolder: '../docs/quiz-grounding/playwright-report', open: 'never' }]],
  outputDir: '../docs/quiz-grounding/e2e-results', workers: 1,
})
