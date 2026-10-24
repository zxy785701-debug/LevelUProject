import { beforeEach, expect, it, vi } from 'vitest'
const state=vi.hoisted(()=>({storage:new Map<string,unknown>(),request:vi.fn()}))
vi.mock('@tarojs/taro',()=>({default:{request:state.request,getStorageSync:(k:string)=>state.storage.get(k),setStorageSync:(k:string,v:unknown)=>state.storage.set(k,v),removeStorageSync:(k:string)=>state.storage.delete(k)}}))
import { saveCredentials } from '../src/credentials'
import { RequestScope } from '../src/api'
import { getImageCapabilities } from '../src/image-api'
import { imageAvailability, imageGenerationMessage } from '../src/image-domain'
import { savePendingStudy, getPendingStudy, generateConfirmed } from '../src/grounding-api'
import { generateKnowledgeQuiz } from '../src/knowledge-api'
import { emptyData } from '../src/domain'
import { stageLabel } from '../src/grounding-domain'
import { knowledgeStage } from '../src/knowledge-domain'

const response=(data:unknown)=>({statusCode:200,data:{code:0,data}})
beforeEach(()=>{vi.clearAllMocks();state.storage.clear();vi.stubGlobal('API_BASE','http://test');saveCredentials('image-user')})

it('配图能力通过鉴权接口读取，额度与服务状态分别呈现',async()=>{
  state.request.mockResolvedValue(response({available:true,remaining:2,daily_limit:20,resolution:'512×512'}))
  const value=await getImageCapabilities()
  expect(value.remaining).toBe(2)
  expect(state.request.mock.calls[0][0]).toMatchObject({url:'http://test/api/v1/quiz/images/capabilities',header:{Authorization:'Bearer image-user'}})
  expect(imageAvailability(value)).toContain('2 / 20')
  expect(imageAvailability({...value,remaining:0})).toContain('额度已用完')
  expect(imageAvailability({...value,available:false,reason_code:'COS_NOT_CONFIGURED'})).toContain('暂未就绪')
})

it('部分失败、额度不足和超时均说明仍可继续作答',()=>{
  expect(imageGenerationMessage()).toBe('')
  expect(imageGenerationMessage({requested:5,generated:2,reason_code:'IMAGE_DAILY_LIMIT'})).toContain('2 / 5')
  expect(imageGenerationMessage({requested:5,generated:2,reason_code:'IMAGE_DAILY_LIMIT'})).toContain('额度不足')
  expect(imageGenerationMessage({requested:3,generated:0,reason_code:'IMAGE_TIMEOUT'})).toContain('正常作答')
  expect(imageGenerationMessage({requested:3,generated:1,reason_code:'IMAGE_PARTIAL_FAILURE'})).toContain('正常作答')
  expect(emptyData().draft.generate_images===true).toBe(false)
})

it('恢复已提交任务时保留当时配图选择，完整图片结果不会被客户端丢弃',async()=>{
  const body={preparation_id:'p',scope_version:1,candidate_ids:['c'],question_count:3 as const,difficulty:'easy' as const,generate_images:true}
  savePendingStudy('user',{kind:'generation',key:'original-key',body,saved_at:1})
  expect(getPendingStudy('user')).toMatchObject({body:{generate_images:true}})
  const session={id:'session',quiz:{id:'quiz',questions:[{id:'q',image_url:'https://images.example.com/a.png'}]},answers:[]}
  state.request.mockResolvedValueOnce(response({kind:'generation_operation',key:'original-key',status:'running',stage:'generating_images',deadline:new Date(Date.now()+390000).toISOString()}))
    .mockResolvedValueOnce(response({status:'succeeded',result:session}))
  expect(await generateConfirmed(body,'original-key',new RequestScope(),()=>{})).toEqual(session)
  expect(state.request.mock.calls[0][0].data.generate_images).toBe(true)
})

it('材料和知识库生成请求均保留明确的配图开关',async()=>{
  const selection={scope_id:'s',scope_version:1,candidate_ids:['topic'],question_count:3 as const,difficulty:'easy' as const,supplement:false,generate_images:true}
  state.request.mockResolvedValue(response({kind:'knowledge_job',id:'job',job_id:'job',job_type:'quiz',status:'queued',stage:'queued',progress:0,deadline:new Date().toISOString()}))
  await generateKnowledgeQuiz(selection,'knowledge-key')
  expect(state.request.mock.calls[0][0].data.generate_images).toBe(true)
  savePendingStudy('user',{kind:'generation',key:'material',body:{material_id:'m',point_ids:['s1'],supplement:false,question_count:5,difficulty:'easy',execution:'background',generate_images:true},saved_at:1})
  expect(getPendingStudy('user')).toMatchObject({body:{generate_images:true,material_id:'m'}})
})

it('配图阶段显示实际进度，超过原文字轮询期限仍在服务端期限内查询',async()=>{
  expect(stageLabel('generating_images')).toBe('正在生成题目配图')
  expect(knowledgeStage('generating_images')).toBe('正在生成题目配图')
  let now=Date.now()
  vi.spyOn(Date,'now').mockImplementation(()=>now)
  const request=new RequestScope()
  vi.spyOn(request,'sleep').mockImplementation(async()=>{now+=350000})
  const body={preparation_id:'p',scope_version:1,candidate_ids:['c'],question_count:3 as const,difficulty:'easy' as const,generate_images:true}
  const running={kind:'generation_operation',key:'slow-images',status:'running',stage:'generating_images',deadline:new Date(now+390000).toISOString()}
  const session={id:'session',quiz:{id:'quiz',questions:[]},answers:[]}
  state.request.mockResolvedValueOnce(response(running)).mockResolvedValueOnce(response(running)).mockResolvedValueOnce(response({status:'succeeded',result:session}))
  try{expect(await generateConfirmed(body,'slow-images',request,()=>{})).toEqual(session)}
  finally{vi.restoreAllMocks()}
})
