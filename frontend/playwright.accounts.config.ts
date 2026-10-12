import { defineConfig } from '@playwright/test'
export default defineConfig({
  testDir: './e2e-accounts', timeout: 60000,
  use: { baseURL: 'http://127.0.0.1:10086', viewport: { width: 390, height: 812 }, headless: true, channel: 'chrome' },
  reporter: [['list'], ['html', { outputFolder: '../docs/user-system/playwright-report', open: 'never' }]],
  outputDir: '../docs/user-system/e2e-results', workers: 1,
})
