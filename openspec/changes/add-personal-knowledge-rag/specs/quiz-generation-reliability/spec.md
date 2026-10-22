# Spec Delta

## ADDED Requirements

### Requirement: Knowledge quizzes reuse core learning lifecycle

The system SHALL 将已确认知识库范围生成的合格题目发布为现有关卡，沿用题型与题量校验、服务端答案隐藏、确认判分、奖励、错题、报告和历史删除。新增来源 MUST 不形成另一套判分或重复奖励链路。

#### Scenario: Complete a knowledge quiz
- **WHEN** 用户确认知识库关卡各题答案并完成末题
- **THEN** 现有服务端判分和一次性奖励规则生效，自动进入现有报告流程并保留来源

#### Scenario: Retry a completed operation
- **WHEN** 用户重复提交或恢复同一已完成知识库生成任务
- **THEN** 返回同一关卡与有效作答状态，不再次扣关卡额度或发放奖励

### Requirement: Knowledge task responses are explicit

The system SHALL 明确区分知识库任务、范围快照和最终 Session，新增任务在小程序短请求中可查询并恢复。客户端 MUST 仅在任务成功且最终关卡可读取时进入答题页，不误将运行状态解析为题库。

#### Scenario: Quiz generation is still running
- **WHEN** 任务返回运行中与当前阶段
- **THEN** 前端保留进度和取消/恢复能力，不进入空白答题页

#### Scenario: Account changes during polling
- **WHEN** 原账号任务响应在用户切换账号后迟到
- **THEN** 客户端不显示该响应，服务端也不允许新账号读取原任务结果

### Requirement: Optional knowledge capability preserves old availability

The system SHALL 允许独立启停知识库入口，缺少 Embedding 配置、索引依赖或执行服务时 MUST 不阻断原应用启动、健康检查、旧主题/材料入口及既有历史。旧接口默认值与同步或后台契约 MUST 保留。

#### Scenario: Embedding service is unconfigured
- **WHEN** 项目启用原有后端而未配置知识库服务
- **THEN** 旧接口与旧关卡仍可使用，知识库入口显示准确的不可用原因

#### Scenario: Legacy clients call existing material APIs
- **WHEN** 旧客户端按既有同步或显式后台模式请求材料出题
- **THEN** 获得原有契约的 Session 或操作结果，不被改为新的知识库任务格式

### Requirement: New and old provenance remains readable in history

The system SHALL 兼容没有知识库字段的旧关卡与包含多文档来源的新关卡，使恢复、重闯、复盘和错题复习保留真实来源状态。功能停止接受新知识库请求后 MUST 仍能读取已发布快照。

#### Scenario: Open a legacy quiz after the extension
- **WHEN** 旧关卡缺少知识库引用字段
- **THEN** 按原兼容规则显示，不默认填入虚构资料或联网状态

#### Scenario: Knowledge entry is disabled after publication
- **WHEN** 用户访问此前生成的知识库关卡与报告
- **THEN** 保留现有读取与作答能力、真实快照和原来源状态，不要求重建原资料
