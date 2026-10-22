import { defineConfig } from '@playwright/test'
import knowledge from './playwright.knowledge.config'
export default defineConfig({ ...knowledge,
  use: { ...knowledge.use, baseURL: process.env.LEVELUP_E2E_UI_ORIGIN || 'http://127.0.0.1:10086' },
  reporter: [['list'], ['html', { outputFolder: '../docs/knowledge-prototype/functional-report', open: 'never' }]],
  outputDir: '../docs/knowledge-prototype/functional-results',
})
