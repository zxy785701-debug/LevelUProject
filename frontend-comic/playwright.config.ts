import { defineConfig } from '@playwright/test'
export default defineConfig({
  testDir: './e2e', timeout: 60000, workers: 1,
  use: { baseURL:'http://127.0.0.1:10087', viewport:{width:375,height:812}, headless:true, channel:'chrome' },
  reporter:[['list'],['html',{outputFolder:'../docs/comic-implementation/playwright-report',open:'never'}]],
  outputDir:'../docs/comic-implementation/e2e-results',
})
