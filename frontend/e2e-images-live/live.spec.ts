// Explicit paid acceptance. No fake model, image, COS or image-response routes.
import {test,expect} from '@playwright/test'
import fs from 'node:fs'
const api='http://127.0.0.1:18001'
const folder='../docs/quiz-images/live-20261024/accepted-live'
fs.mkdirSync(folder,{recursive:true})

test('真实资料五题配图、答题、历史回看和重闯复用',async({page,request})=>{
  const errors:string[]=[]
  const generatedBodies:any[]=[]
  page.on('pageerror',error=>errors.push(error.message))
  await page.route('**/api/v1/**',async route=>{
    const url=new URL(route.request().url());url.port='18001'
    const response=await route.fetch({url:url.toString(),timeout:300000})
    if(url.pathname==='/api/v1/quiz/generate')generatedBodies.push(await response.json())
    await route.fulfill({response})
  })
  const loginCode='image-real-full-'+Date.now()
  const login=await request.post(api+'/api/v1/auth/wechat',{data:{
    code:loginCode,agreement_version:'2026-10-12'}})
  expect(login.ok()).toBeTruthy()
  const account=(await login.json()).data
  const headers={Authorization:'Bearer '+account.token}
  await page.goto('/')
  await page.evaluate(token=>localStorage.setItem('levelup.auth.v1',JSON.stringify({data:{token},expire:null})),account.token)
  await page.reload()
  await expect(page.locator('textarea')).toBeVisible()
  await expect(page.getByText('正在同步云端学习记录…')).toHaveCount(0)
  const before=(await (await request.get(api+'/api/v1/quiz/images/capabilities',{headers})).json()).data
  expect(before.remaining).toBe(20)
  await page.getByText('出题设置',{exact:false}).click()
  await page.getByText('5 题',{exact:true}).click()
  await page.locator('.image-choice taro-switch-core').click()
  await page.getByText('文档',{exact:true}).click()
  const chooser=page.waitForEvent('filechooser')
  await page.getByText('点击选择一份文档',{exact:true}).click()
  await (await chooser).setFiles({name:'fruit-vocabulary.txt',mimeType:'text/plain',buffer:Buffer.from(
    '英语水果词汇学习资料。apple 的中文意思是苹果。banana 的中文意思是香蕉。orange 的中文意思是橙子。grape 的中文意思是葡萄。pear 的中文意思是梨。这五个词都表示水果。apple 与 pear 是不同的水果，banana 与 grape 也不相同。学习目标是掌握这五个英语单词和中文名称的一一对应关系。')})
  await page.getByText('解析这份文档',{exact:true}).click()
  await expect(page.getByText('确认范围，生成关卡',{exact:true})).toBeVisible({timeout:180000})
  const started=Date.now()
  await page.getByText('确认范围，生成关卡',{exact:true}).click()
  await expect(page.getByText('开始这一关',{exact:true})).toBeVisible({timeout:180000})
  const elapsed=(Date.now()-started)/1000
  await page.getByText('开始这一关',{exact:true}).click()
  const active=(await (await request.get(api+'/api/v1/attempts',{headers})).json()).data.items.find((item:any)=>!item.completed_at)
  expect(active.quiz.image_generation.generated).toBe(5)
  const first=page.locator('.question-image img')
  await expect(first).toBeVisible()
  await expect.poll(()=>first.evaluate((img:HTMLImageElement)=>img.complete&&img.naturalWidth===512)).toBeTruthy()
  const imageUrl=await first.getAttribute('src')
  for(const width of [390,320]){
    await page.setViewportSize({width,height:812})
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy()
    await page.screenshot({path:`${folder}/question-${width}.png`})
  }
  await page.setViewportSize({width:390,height:812})
  const decodedImages=[]
  for(let i=0;i<5;i++){
    await expect(page.locator('.question')).toHaveText(active.quiz.questions[i].stem)
    const image=page.locator('.question-image img')
    await expect(image).toBeVisible()
    await expect.poll(()=>image.evaluate((img:HTMLImageElement)=>img.complete&&img.naturalWidth===512)).toBeTruthy()
    decodedImages.push(await image.getAttribute('src'))
    await page.locator('.option').first().click()
    // Multi-select needs at least two choices. Frontend labels the question type.
    if(await page.getByText('多选题',{exact:true}).isVisible())await page.locator('.option').nth(1).click()
    await page.getByText('确认本题',{exact:true}).click()
    if(i<4){await expect(page.locator('.feedback')).toBeVisible();await page.getByText('下一题',{exact:true}).click()}
  }
  await expect(page.getByText('本轮答案与解析',{exact:true})).toBeVisible({timeout:90000})
  await expect.poll(async()=>Boolean((await (await request.get(api+'/api/v1/attempts/'+active.id,{headers})).json()).data.report),{timeout:90000}).toBeTruthy()
  await expect(page.getByText('成绩和答案已就绪，正在补充学习总结…',{exact:true})).toHaveCount(0,{timeout:90000})
  await expect(page.getByText('三句话，带走这关',{exact:true})).toBeVisible()
  await page.getByText('逐题回看',{exact:true}).click()
  await page.locator('.question-records .list-row').first().click()
  await expect(page.locator('.question-image img')).toHaveAttribute('src',imageUrl!)
  await page.screenshot({path:folder+'/history.png'})
  await page.locator('.mini-back').click()
  await page.getByText('再闯一次这一关',{exact:true}).click()
  await page.getByText('开始这一关',{exact:true}).click()
  await expect(page.locator('.question-image img')).toHaveAttribute('src',imageUrl!)
  const after=(await (await request.get(api+'/api/v1/quiz/images/capabilities',{headers})).json()).data
  const metrics=await (await request.get(api+'/__live_metrics')).json()
  const attempts=(await (await request.get(api+'/api/v1/attempts',{headers})).json()).data.items
  const old=attempts.find((item:any)=>item.completed_at)
  expect(old).toBeTruthy()
  const relogin=(await (await request.post(api+'/api/v1/auth/wechat',{data:{code:loginCode,agreement_version:'2026-10-12'}})).json()).data
  expect(relogin.user.id).toBe(account.user.id)
  const restored=(await (await request.get(api+'/api/v1/attempts/'+old.id,
    {headers:{Authorization:'Bearer '+relogin.token}})).json()).data
  expect(restored.quiz.questions.map((q:any)=>q.image_url)).toEqual(decodedImages)
  expect(after.remaining).toBe(15)
  expect(metrics.image_calls).toHaveLength(5)
  expect(metrics.maximum_concurrency).toBeGreaterThanOrEqual(2)
  expect(metrics.maximum_concurrency).toBeLessThanOrEqual(5)
  expect(new Set(decodedImages).size).toBe(5)
  expect(errors).toEqual([])
  fs.writeFileSync(folder+'/browser-acceptance.json',JSON.stringify({user_id:account.user.id,
    elapsed_seconds:elapsed,quota_before:before.remaining,quota_after:after.remaining,
    decoded_images:decodedImages,maximum_concurrency:metrics.maximum_concurrency,
    generated_responses:generatedBodies,attempts,errors},null,2))
})
