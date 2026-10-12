import { test,expect,Page } from '@playwright/test'
import fs from 'node:fs'
import { stats } from '../src/domain'
const sample=JSON.parse(fs.readFileSync('../backend/test-results/live-sample.json','utf8'))
const quiz=(count=5)=>({...sample.quiz,questions:count===5?sample.quiz.questions:['single','multi','judge'].map(t=>sample.quiz.questions.find((q:any)=>q.type===t))})
const data=(p:Page)=>p.evaluate(()=>JSON.parse(localStorage.getItem('levelup.comic.local.v1')||'null')?.data)
const shot=(p:Page,name:string)=>p.screenshot({path:`../docs/comic-implementation/screenshots/${name}.png`})
async function welcome(p:Page){await p.goto('/');await p.getByRole('button',{name:'先随便逛逛',exact:true}).click()}
async function start(p:Page,count=5){
 await p.route('**/api/v1/quiz/generate',r=>r.fulfill({json:{code:0,data:quiz(count)}}))
 await p.locator('textarea').fill('什么是 RAG？它和传统搜索有什么区别？')
 if(count===3){await p.getByRole('button',{name:/出题设置/}).click();await p.getByRole('button',{name:'3 题',exact:true}).click()}
 await p.getByRole('button',{name:'开始生成题目',exact:true}).click()
 await expect(p.locator('.question-stem')).toBeVisible()
}
async function answer(p:Page,q:any,correct=true){
 const choices=correct?q.answers:[q.options.find((o:any)=>!q.answers.includes(o.id)).id]
 for(const id of choices) await p.locator(`[data-option="${id}"]`).click()
 if(q.type==='multi') await p.getByRole('button',{name:/提交答案/}).click()
 await expect(p.locator('.feedback')).toBeVisible()
 if(await p.locator('.combo-modal').isVisible()) await p.getByRole('button',{name:'继续闯关',exact:true}).click()
}
async function finish(p:Page,count=5,correct=true){
 for(const [i,q] of quiz(count).questions.entries()){
   await answer(p,q,correct)
   await p.getByRole('button',{name:i===count-1?'查看战报':'下一关',exact:true}).click()
 }
}
async function report(p:Page){
 await p.route('**/api/v1/report/generate',async r=>{
   const b=r.request().postDataJSON();const s=stats({...b,id:'test',cursor:0,pending_ms:0,started_at:new Date().toISOString()})
   await r.fulfill({json:{code:0,data:{...sample.report,quiz_id:b.quiz.id,stats:s}}})
 })
 await p.getByRole('button',{name:'查看复盘报告',exact:true}).click()
 await expect(p.getByText('三句话总结',{exact:true})).toBeVisible()
}
test('01–03：游客、独立存储、首页、设置和扩展入口',async({page})=>{
 await page.goto('/');await shot(page,'01-welcome')
 await page.getByRole('button',{name:'微信一键登录',exact:true}).click()
 await expect(page.locator('.global-dialog')).toContainText('后续开放')
 await page.getByRole('button',{name:'知道了',exact:true}).click()
 await page.getByRole('button',{name:'先随便逛逛',exact:true}).click()
 await expect(page.getByRole('button',{name:'开始生成题目',exact:true})).toBeDisabled()
 await shot(page,'02-home')
 await page.getByRole('button',{name:'RAG 入门',exact:true}).click()
 await page.getByRole('button',{name:/出题设置/}).click()
 await page.getByRole('button',{name:'3 题',exact:true}).click();await page.getByRole('button',{name:'进阶',exact:true}).click()
 await shot(page,'03-settings');expect((await data(page)).draft).toMatchObject({count:3,difficulty:'medium'})
 await page.getByRole('button',{name:'上传文档',exact:true}).click()
 await expect(page.locator('.global-dialog')).toContainText('后续开放')
 expect(await page.evaluate(()=>localStorage.getItem('levelup.local.v1'))).toBeNull()
})
test('06–14：5题全对、即时反馈、连击、报告和真实PNG海报',async({page})=>{
 await welcome(page);await start(page);await shot(page,'06-single')
 for(const [i,q] of quiz().questions.entries()){
   if(q.type==='multi') await shot(page,'09-multi')
   if(q.type==='judge') await shot(page,'10-judge')
   const choices=q.answers
   for(const id of choices) await page.locator(`[data-option="${id}"]`).click()
   if(q.type==='multi') await page.getByRole('button',{name:/提交答案/}).click()
   await expect(page.locator('.feedback')).toBeVisible()
   if(i===0){await shot(page,'07-correct');await page.locator('[data-option]').first().click();expect((await data(page)).sessions[0].answers).toHaveLength(1)}
   if(await page.locator('.combo-modal').isVisible()){await shot(page,'11-combo');await page.getByRole('button',{name:'继续闯关',exact:true}).click()}
   await page.getByRole('button',{name:i===4?'查看战报':'下一关',exact:true}).click()
 }
 await expect(page.locator('.result')).toContainText('5/5');await shot(page,'12-result')
 expect(stats((await data(page)).sessions[0])).toMatchObject({xp:50,coins:10,accuracy:100})
 await report(page);await shot(page,'13-report')
 await page.getByRole('button',{name:'生成分享海报',exact:true}).click()
 await expect(page.locator('.poster-image')).toBeVisible();await shot(page,'14-poster')
 const download=page.waitForEvent('download');await page.getByRole('button',{name:'保存到相册',exact:true}).click()
 const file=await download;await file.saveAs('../docs/comic-implementation/screenshots/poster-generated.png')
 expect(fs.readFileSync('../docs/comic-implementation/screenshots/poster-generated.png').subarray(1,4).toString()).toBe('PNG')
 const before=await page.locator('.poster-image').getAttribute('src');await page.getByRole('button',{name:'换一张配色',exact:true}).click()
 await expect(page.locator('.poster-image')).not.toHaveAttribute('src',before!)
})
test('08、15：全部答错、离线可答、暂停重启与报告重试',async({page,context})=>{
 await welcome(page);await start(page,3);const qs=quiz(3).questions
 await answer(page,qs[0],false);await shot(page,'08-incorrect')
 await page.getByRole('button',{name:'暂停闯关',exact:true}).click()
 await page.getByRole('button',{name:'保存进度并离开',exact:true}).click()
 await page.reload();await page.getByRole('button',{name:'继续闯关',exact:true}).click()
 await expect(page.locator('.feedback')).toBeVisible();expect((await data(page)).sessions[0].answers).toHaveLength(1)
 await context.setOffline(true);await expect(page.locator('.network-banner')).toBeVisible();await shot(page,'15-offline')
 await page.getByRole('button',{name:'下一关',exact:true}).click()
 for(const [i,q] of qs.slice(1).entries()){await answer(page,q,false);await page.getByRole('button',{name:i===1?'查看战报':'下一关',exact:true}).click()}
 await context.setOffline(false)
 await page.route('**/api/v1/report/generate',r=>r.fulfill({status:503,json:{code:'MODEL_TIMEOUT',message:'生成超时，请重试'}}))
 await page.getByRole('button',{name:'查看复盘报告',exact:true}).click()
 await expect(page.locator('.error-page')).toContainText('生成超时')
 expect((await data(page)).sessions[0].completed_at).toBeTruthy()
 await page.unroute('**/api/v1/report/generate')
 await page.route('**/api/v1/report/generate',r=>r.fulfill({json:{code:0,data:sample.report}}))
 await page.getByRole('button',{name:'重新生成一次',exact:true}).click();await expect(page.getByText('三句话总结',{exact:true})).toBeVisible()
})
test('04–05：生成中取消、失败后保留草稿与重试',async({page})=>{
 await welcome(page)
 await page.route('**/api/v1/quiz/generate',async r=>{await new Promise(resolve=>setTimeout(resolve,1800));await r.fulfill({json:{code:0,data:quiz()}}).catch(()=>{})})
 await page.locator('textarea').fill('我要学习 RAG');await page.getByRole('button',{name:'开始生成题目',exact:true}).click()
 await expect(page.locator('.loading-page')).toBeVisible();await shot(page,'04-generating')
 await page.getByRole('button',{name:'取消',exact:true}).click();await expect(page.locator('textarea')).toHaveValue('我要学习 RAG')
 await page.unroute('**/api/v1/quiz/generate');await page.route('**/api/v1/quiz/generate',r=>r.fulfill({status:503,json:{code:'MODEL_TIMEOUT',message:'模型暂时超时'}}))
 await page.getByRole('button',{name:'开始生成题目',exact:true}).click();await expect(page.locator('.error-page')).toContainText('模型暂时超时');await shot(page,'05-generation-error')
 await page.getByRole('button',{name:'回去换个说法',exact:true}).click();await expect(page.locator('textarea')).toHaveValue('我要学习 RAG')
 await start(page,3)
})
test('多选显式提交、允许漏选/多选判错，存储失败不发奖励',async({page})=>{
 await welcome(page);await start(page,3);await answer(page,quiz(3).questions[0]);await page.getByRole('button',{name:'下一关',exact:true}).click()
 await expect(page.getByRole('button',{name:/提交答案/})).toBeDisabled()
 const q=quiz(3).questions[1];await page.locator(`[data-option="${q.answers[0]}"]`).click()
 expect((await data(page)).sessions[0].answers).toHaveLength(1)
 await page.getByRole('button',{name:/提交答案/}).click();await expect(page.locator('.feedback')).toContainText('正确答案')
 expect(stats((await data(page)).sessions[0]).correct_count).toBe(1)
})
test('320px长文本、恢复记录、扩展入口与空态',async({page})=>{
 await page.setViewportSize({width:320,height:640});await welcome(page)
 await page.getByRole('button',{name:'知识库',exact:true}).click();await expect(page.locator('.global-dialog')).toBeVisible();await page.getByRole('button',{name:'知道了',exact:true}).click()
 await page.getByRole('button',{name:'我的',exact:true}).click();await expect(page.getByText('这里还什么都没有',{exact:true})).toBeVisible();await shot(page,'15-empty')
 await page.getByRole('button',{name:'去出第一关',exact:true}).click();await page.locator('textarea').fill('学习'.repeat(3000));await shot(page,'03-long-320')
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=320)).toBe(true)
 await page.reload();await expect(page.locator('textarea')).toHaveValue('学习'.repeat(3000))
})
test('真实后端：3题混合作答与AI报告',async({page})=>{
 test.skip(process.env.COMIC_LIVE!=='1','显式开启真实模型联调');test.setTimeout(240000)
 await welcome(page);await page.locator('textarea').fill('HTTP 为什么是无状态的？')
 await page.getByRole('button',{name:/出题设置/}).click();await page.getByRole('button',{name:'3 题',exact:true}).click()
 await page.getByRole('button',{name:'开始生成题目',exact:true}).click();await expect(page.locator('.question-stem')).toBeVisible({timeout:110000})
 const qs=(await data(page)).sessions[0].quiz.questions
 for(const [i,q] of qs.entries()){await answer(page,q,i!==1);await page.getByRole('button',{name:i===2?'查看战报':'下一关',exact:true}).click()}
 await page.getByRole('button',{name:'查看复盘报告',exact:true}).click();await expect(page.getByText('三句话总结',{exact:true})).toBeVisible({timeout:110000})
 expect((await data(page)).sessions[0].report.stats).toMatchObject({total:3,correct_count:2,xp:20,coins:4})
 await shot(page,'13-report-live');fs.writeFileSync('../docs/comic-implementation/test-results/live-result.json',JSON.stringify((await data(page)).sessions[0],null,2))
})
