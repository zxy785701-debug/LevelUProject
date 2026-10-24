import {defineConfig} from '@playwright/test'
export default defineConfig({
  testDir:'./e2e-images-live',workers:1,timeout:300000,
  testMatch:process.env.LEVELUP_IMAGE_LIVE_TOKEN?'reuse.spec.ts':'live.spec.ts',
  use:{baseURL:'http://127.0.0.1:18086',viewport:{width:390,height:812},headless:true,channel:'chrome',screenshot:'only-on-failure'},
  reporter:[['list'],['json',{outputFile:'../docs/quiz-images/live-20261024/accepted-live/browser.json'}]],
  outputDir:'../docs/quiz-images/live-20261024/accepted-live/browser-results',
})
