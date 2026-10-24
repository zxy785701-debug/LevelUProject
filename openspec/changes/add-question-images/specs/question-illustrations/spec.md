# Question illustrations

## Purpose

为用户主动选择的学习关卡提供与题目内容相关的辅助图片，覆盖全部出题来源和后续学习回看，并通过独立额度、持久化与失败降级维持原有学习流程的可靠性。

## ADDED Requirements

### Requirement: Image generation is explicitly optional
系统 SHALL 为主题、材料和知识库关卡提供默认关闭的配图开关，并在确认生成时固定该选择；旧请求和旧题库 MUST 继续可用。

#### Scenario: Default and legacy requests
- **WHEN** 用户未启用配图或旧客户端未提供开关
- **THEN** 不调用生图服务，原有题量、审核、判分、奖励及恢复行为保持有效

#### Scenario: All learning sources
- **WHEN** 用户为主题、文档、网页、视频或知识库闯关开启配图
- **THEN** 系统在题目审核通过后尝试为每道题生成一张相关图片

### Requirement: Related images are stored durably
系统 SHALL 生成 512×512 辅助图片，将图片转存对象存储后保存长期可访问的 HTTPS URL；MUST NOT 将临时服务地址作为最终题目图片。

#### Scenario: Successful generation
- **WHEN** 生图、下载及上传均成功
- **THEN** 对应题目保存长期图片 URL，多个题目的结果不会错配

### Requirement: Image prompts describe scenes without quiz text
系统 SHALL 使用现有文字模型批量生成纯画面描述，生图输入不得包含原始题干、选项、答案或解析。描述步骤 MUST 遵守现有模型预算与图片阶段时限，持久复用已保存计划；失败时正常发布文字题目。

#### Scenario: Plan recovery and unavailable planning
- **WHEN** 同一操作恢复或描述模型失败、预算耗尽
- **THEN** 已保存描述不重复调用，未知结果不自动重发；失败不发起带题干的生图请求且不扣生图额度

### Requirement: Daily image requests are bounded per identity
系统 SHALL 默认每个身份每个上海自然日最多发起 20 次生图请求，阈值可配置；实际开始的失败请求计入额度，未开始的请求不计入，同一操作同一题目不得重复发起。

#### Scenario: Remaining quota partially covers a quiz
- **WHEN** 五题关卡只有两张剩余额度
- **THEN** 最多调用两次生图，其余题目正常返回文字并显示额度不足提示

#### Scenario: Concurrent requests and recovery
- **WHEN** 同一身份的请求并发或原操作被重复查询、恢复
- **THEN** 总请求数不超过日上限，已开始或已完成的题目不会重复扣减和生成

#### Scenario: Upstream request pacing
- **WHEN** API 或知识库 Worker 并发为多题配图
- **THEN** 默认共享至少 0.55 秒发送间隔，最多五张在途；等待发送中取消或超时不消耗实际生图额度

#### Scenario: Midnight and account deletion
- **WHEN** 上海日期变化或用户当天注销后重新注册
- **THEN** 新日期额度重置，当天同一身份的已发生计数不会因重新注册清零

### Requirement: Image failures cannot fail a valid text quiz
系统 MUST 独立限制图片生成、下载和上传的等待；配置缺失、额度耗尽、服务错误或部分图片失败时 SHALL 正常发布已审核文字题目并提供友好说明。

#### Scenario: Partial or total provider failure
- **WHEN** 一题或全部图片生成、下载、上传失败或超时
- **THEN** 保留成功配图，失败题目不带图片，文字题目和原有依据状态正常返回

### Requirement: Existing learning pages reuse stored images
系统 SHALL 在答题、逐题回看、报告解析及错题详情展示可用配图；重闯及错题复习 MUST 复用原图且不消耗生图额度。图片加载失败不得阻止作答。

#### Scenario: Replay and history
- **WHEN** 用户重新登录后回看、重闯或复习有配图的题目
- **THEN** 展示原图且不发起新的生图请求

### Requirement: Image service configuration remains server owned
系统 MUST 从环境变量读取云端凭据和存储配置，禁止客户端指定生图端点、图片下载地址、存储键或密钥。可选配置错误不得影响文字功能启动。

#### Scenario: Unavailable optional configuration
- **WHEN** COS 或生图配置缺失、格式错误或可选 SDK 不可用
- **THEN** 能力查询返回不可用说明，核心健康检查和文字学习仍可运行
