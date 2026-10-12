import { defineConfig } from '@playwright/test'
export default defineConfig({
  testDir: './e2e',
  timeout: 60000,
  use: {
    baseURL: 'http://127.0.0.1:10086',
    viewport: { width: 390, height: 812 },
    headless: true,
    channel: 'chrome',
  },
  reporter: [
    ['list'],
    ['html', { outputFolder: '../docs/implementation/playwright-report', open: 'never' }],
  ],
  outputDir: '../docs/implementation/e2e-results',
  workers: 1,
})
