import { describe, it, expect, vi, beforeEach } from 'vitest'
const mock=vi.hoisted(()=>({request:vi.fn()}))
vi.mock('@tarojs/taro',()=>({default:{request:mock.request}}))
import { generateQuiz, generateReport, cancelRequest } from '../src/api'
describe('真实 API 协议与失败恢复',()=>{
  beforeEach(()=>{mock.request.mockReset()})
  it('发送后端支持的出题字段与超时',async()=>{
    mock.request.mockResolvedValue({statusCode:200,data:{code:0,data:{id:'quiz'}}})
    expect(await generateQuiz('HTTP',3,'medium')).toEqual({id:'quiz'})
    expect(mock.request).toHaveBeenCalledWith(expect.objectContaining({url:'http://127.0.0.1:8000/api/v1/quiz/generate',method:'POST',data:{text:'HTTP',question_count:3,difficulty:'medium'},timeout:100000}))
  })
  it('保留后端错误码与可读提示',async()=>{
    mock.request.mockResolvedValue({statusCode:503,data:{code:'MODEL_NOT_CONFIGURED',message:'请先配置模型'}})
    await expect(generateQuiz('HTTP',5,'easy')).rejects.toMatchObject({code:'MODEL_NOT_CONFIGURED',message:'请先配置模型'})
  })
  it.each([null,{},'html'])('网络或非 JSON 错误不使页面崩溃：%s',async body=>{
    mock.request.mockResolvedValue({statusCode:502,data:body})
    await expect(generateQuiz('HTTP',5,'easy')).rejects.toBeInstanceOf(Error)
  })
  it('取消请求调用任务 abort，网络断开给出重试提示',async()=>{
    const abort=vi.fn(), task=Object.assign(Promise.reject(new Error('offline')),{abort})
    mock.request.mockReturnValue(task)
    const response=generateQuiz('HTTP',5,'easy'); cancelRequest()
    await expect(response).rejects.toMatchObject({code:'NETWORK_ERROR'})
    expect(abort).toHaveBeenCalledOnce()
  })
  it('报告传递原题库、逐题答案和模式，不传客户端得分',async()=>{
    mock.request.mockResolvedValue({statusCode:200,data:{code:0,data:{quiz_id:'q'}}})
    const s={quiz:{id:'q'},answers:[{question_id:'1',selected:['A'],elapsed_ms:200}],mode:'new'}
    await generateReport(s as any)
    expect(mock.request).toHaveBeenCalledWith(expect.objectContaining({data:s,url:expect.stringContaining('/report/generate')}))
  })
})
