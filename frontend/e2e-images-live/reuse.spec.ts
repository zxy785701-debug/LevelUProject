import {test,expect} from '@playwright/test'

test('既有真实图片在重新登录后继续重闯展示',async({page})=>{
  test.skip(!process.env.LEVELUP_IMAGE_LIVE_TOKEN,'Requires in-memory test-session handoff')
  await page.route('**/api/v1/**',async route=>{
    const url=new URL(route.request().url());url.port='18001'
    await route.fulfill({response:await route.fetch({url:url.toString()})})
  })
  await page.goto('/')
  await page.evaluate(token=>localStorage.setItem('levelup.auth.v1',JSON.stringify({data:{token},expire:null})),process.env.LEVELUP_IMAGE_LIVE_TOKEN!)
  await page.reload()
  await expect(page.getByText('正在同步云端学习记录…')).toHaveCount(0)
  await page.getByText('已完成 0 / 5 题',{exact:true}).click()
  const image=page.locator('.question-image img')
  await expect(image).toHaveAttribute('src',process.env.LEVELUP_IMAGE_FIRST_URL!)
  await expect.poll(()=>image.evaluate((img:HTMLImageElement)=>img.complete&&img.naturalWidth===512)).toBeTruthy()
  await page.screenshot({path:'../docs/quiz-images/live-20261024/final-live/replay.png'})
})
