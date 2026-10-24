import { test, expect, Page, APIRequestContext } from '@playwright/test'
import fs from 'node:fs'
const origin='http://127.0.0.1:18001'
const folder='../docs/quiz-images/screenshots'
const pageErrors=new WeakMap<Page,string[]>()
fs.mkdirSync(folder,{recursive:true})
test.beforeEach(async({page})=>{
  const errors:string[]=[];pageErrors.set(page,errors)
  page.on('pageerror',error=>errors.push(error.message))
  await page.route('**/api/v1/**',async route=>{
    const url=new URL(route.request().url());url.port='18001'
    await route.fulfill({response:await route.fetch({url:url.toString()})})
  })
  await page.route('https://images.example.com/**',route=>route.fulfill({path:'e2e-images/fixture.png',contentType:'image/png'}))
})
test.afterEach(async({page})=>{await page.unrouteAll({behavior:'wait'});expect(pageErrors.get(page)).toEqual([])})
async function login(page:Page,request:APIRequestContext){
  const response=await request.post(origin+'/api/v1/auth/wechat',{data:{code:'image-browser-'+Date.now()+Math.random(),agreement_version:'2026-10-12'}})
  expect(response.status()).toBe(200)
  const account=(await response.json()).data
  await page.goto('/')
  await page.evaluate(token=>localStorage.setItem('levelup.auth.v1',JSON.stringify({data:{token},expire:null})),account.token)
  await page.reload();await expect(page.locator('textarea')).toBeVisible()
  await expect(page.getByText('正在同步云端学习记录…')).toHaveCount(0)
  return {Authorization:'Bearer '+account.token}
}
async function snapshot(page:Page,name:string){
  for(const width of [390,320]){
    await page.setViewportSize({width,height:812})
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy()
    await page.screenshot({path:folder+'/'+name+'-'+width+'.png'})
  }
  await page.setViewportSize({width:390,height:812})
}
async function topic(page:Page,images=true){
  await page.locator('textarea').fill('HTTP 与会话')
  await page.getByText('出题设置',{exact:false}).click()
  await page.getByText('3 题',{exact:true}).click()
  const toggle=page.locator('.image-choice taro-switch-core')
  await expect(toggle).not.toHaveAttribute('checked','true')
  if(images){await toggle.click();await expect(toggle).toHaveAttribute('checked','true')}
  await snapshot(page,images?'settings':'disabled-settings')
  await page.getByText('生成我的关卡',{exact:false}).click()
  await expect(page.locator('.image-choice taro-switch-core')).toHaveAttribute('checked',String(images))
  const sent=page.waitForRequest(r=>r.url().endsWith('/api/v1/quiz/generate'))
  await page.getByText('确认范围，生成关卡',{exact:true}).click()
  expect((await sent).postDataJSON().generate_images).toBe(images)
  await page.getByText('开始这一关',{exact:true}).click()
}

test('配图开关→答题与坏图降级→报告→历史回看→重闯复用，320/390px',async({page,request})=>{
  const headers=await login(page,request)
  await topic(page)
  await expect(page.locator('.question-image img')).toBeVisible()
  await expect(page.getByText('配图加载中…',{exact:true})).toHaveCount(0)
  await snapshot(page,'question')
  const first=await page.locator('.question-image img').getAttribute('src')
  await page.route('https://images.example.com/**',route=>route.abort())
  for(let i=0;i<3;i++){
    await expect(page.locator('.question')).toHaveText(`第 ${i+1} 个问题？`)
    if(i>0)await expect(page.getByText('配图暂时无法加载，可以继续答题。',{exact:true})).toBeVisible()
    await page.locator('.option').nth(i===0?1:0).click()
    if(i===1)await page.locator('.option').nth(1).click()
    await page.getByText('确认本题',{exact:true}).click()
    if(i<2){await expect(page.locator('.feedback')).toBeVisible();await page.getByText('下一题',{exact:true}).click()}
  }
  await expect(page.getByText('本轮答案与解析',{exact:true})).toBeVisible()
  await page.unroute('https://images.example.com/**')
  await page.route('https://images.example.com/**',route=>route.fulfill({path:'e2e-images/fixture.png',contentType:'image/png'}))
  await page.getByText('再巩固一下薄弱知识',{exact:true}).click()
  await page.getByText('第 1 个问题？',{exact:true}).click()
  await expect(page.locator('.question-image img')).toHaveAttribute('src',first!)
  await snapshot(page,'wrong-question')
  await page.locator('.mini-back').click()
  await page.locator('.mini-back').click()
  await page.getByText('逐题回看',{exact:true}).click()
  await page.getByText('第 1 个问题？',{exact:true}).click()
  await expect(page.locator('.question-image img')).toHaveAttribute('src',first!)
  await snapshot(page,'history-question')
  await page.locator('.mini-back').click()
  await page.getByText('再闯一次这一关',{exact:true}).click()
  await page.getByText('开始这一关',{exact:true}).click()
  await expect(page.locator('.question-image img')).toHaveAttribute('src',first!)
  const quota=(await (await request.get(origin+'/api/v1/quiz/images/capabilities',{headers})).json()).data
  expect(quota.remaining).toBe(17)
})

for(const available of [false,true])test(available?'额度用完仍可正常出文字题目':'服务未配置仍可正常出文字题目',async({page,request})=>{
  await page.route('**/api/v1/quiz/images/capabilities',route=>route.fulfill({json:{code:0,data:{available,remaining:0,daily_limit:20,reason_code:available?null:'COS_NOT_CONFIGURED',resolution:'512×512'}}}))
  await login(page,request)
  await topic(page,false)
  await expect(page.locator('.question-illustration')).toHaveCount(0)
  await expect(page.locator('.option')).toHaveCount(4)
})

test('材料来源同样提交配图选择',async({page,request})=>{
  await login(page,request)
  await page.getByText('文档',{exact:true}).click()
  const chooser=page.waitForEvent('filechooser')
  await page.getByText('点击选择一份文档',{exact:true}).click()
  await (await chooser).setFiles({name:'image-source.txt',mimeType:'text/plain',buffer:Buffer.from('HTTP 每次请求独立。Cookie 用来保存状态。Session 保存会话信息。')})
  await page.getByText('解析这份文档',{exact:true}).click()
  await expect(page.locator('.image-choice')).toBeVisible()
  await page.locator('.image-choice taro-switch-core').click()
  const sent=page.waitForRequest(r=>r.url().endsWith('/api/v1/quiz/generate'))
  await page.getByText('确认范围，生成关卡',{exact:true}).click()
  expect((await sent).postDataJSON().generate_images).toBe(true)
  await page.getByText('开始这一关',{exact:true}).click()
  await expect(page.locator('.question-image img')).toBeVisible()
})

test('知识库出题设置默认关闭，配图选择按账号保存',async({page,request})=>{
  const data={enabled:true,available:true,embedding_available:true,web_available:false,worker:{status:'ready',heartbeat_at:null},formats:['txt'],limits:{max_bytes:100000,max_documents:100,question_max_chars:6000},disclosure:'测试资料库'}
  await page.route('**/api/v1/knowledge/capabilities',route=>route.fulfill({json:{code:0,data}}))
  await page.route('**/api/v1/knowledge/documents?*',route=>route.fulfill({json:{code:0,data:{items:[],total:0,page:1,page_size:20}}}))
  await login(page,request)
  await page.getByText('我的',{exact:true}).click()
  await page.getByText('私有知识库',{exact:true}).click()
  await page.getByRole('button',{name:'根据资料出题',exact:true}).click()
  await page.getByRole('button',{name:/出题设置/}).click()
  const toggle=page.locator('.image-choice taro-switch-core')
  await expect(toggle).not.toHaveAttribute('checked','true')
  await toggle.click()
  await expect(toggle).toHaveAttribute('checked','true')
  await snapshot(page,'knowledge-settings')
  expect(await page.evaluate(()=>Object.keys(localStorage).some(key=>key.startsWith('levelup.knowledge.draft.v1:') && JSON.parse(localStorage.getItem(key)!).data.generate_images===true))).toBeTruthy()
})
