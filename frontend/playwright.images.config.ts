import { defineConfig } from '@playwright/test'
export default defineConfig({
  testDir: './e2e-images', timeout: 90000, workers: 1,
  use: { baseURL: 'http://127.0.0.1:18086', viewport: { width: 390, height: 812 }, headless: true, channel: 'chrome' },
  reporter: [['list'], ['json', { outputFile: '../docs/quiz-images/test-results/browser.json' }], ['html', { outputFolder: '../docs/quiz-images/playwright-report', open: 'never' }]],
  outputDir: '../docs/quiz-images/browser-results',
})
