# Spec Delta

## Purpose

为知识库导入、检索问答和出题提供脱离客户端连接的持久任务，使用户能够在短请求中获知进展，并在切后台、网络中断或服务重启后继续获取真实且一致的结果。

## ADDED Requirements

### Requirement: Short requests and durable job identity

The system SHALL 在完成输入接收与校验、持久保存任务后返回任务标识，由后台执行新增耗时流程。客户端 SHALL 通过受鉴权的短请求查询状态，不依赖一条超过小程序请求时限的连接。

#### Scenario: Start a lengthy document import
- **WHEN** 文件已接收且资料与任务保存成功
- **THEN** 请求返回处理中及任务标识，解析和向量化由后台继续执行

#### Scenario: Reopen the mini program
- **WHEN** 用户关闭页面后使用同一账号回来
- **THEN** 可以通过持久任务标识恢复查询，无须重新触发相同操作

### Requirement: Monotonic progress and explicit terminal results

The system SHALL 提供排队、运行、成功、失败和取消状态及阶段信息，同一任务的用户可见进度 MUST 不下降，只有成功完成才到 100%。失败 MUST 返回可行动说明，并区分资料不足与技术故障。

#### Scenario: Worker resumes from a checkpoint
- **WHEN** 已显示 70% 的任务中断后恢复
- **THEN** 显示进度不退回早期阶段的较小百分比，当前阶段说明仍真实

#### Scenario: Provider credentials fail
- **WHEN** 外部服务拒绝当前凭据
- **THEN** 任务结束并说明配置不可用，不无限停留在进度页或盲目重试

### Requirement: Idempotent submission and atomic publication

The system SHALL 对同账号同类操作的幂等提交返回同一操作身份，成功结果与任务完成 MUST 一致发布。重试、重复轮询和网络重发 MUST NOT 产生重复资料版本、关卡、答题尝试或奖励。

#### Scenario: Client resends a quiz request
- **WHEN** 首次提交响应丢失，客户端携相同幂等键再次提交
- **THEN** 获得原操作及其状态，不额外生成关卡或重复扣除闯关额度

#### Scenario: Process fails around final publication
- **WHEN** 执行器在最终结果发布边界中断
- **THEN** 恢复后只有一个已发布结果，任务与结果可以一致对账

### Requirement: Fenced recovery and bounded attempts

The system SHALL 在执行进程重启或租约失效后从有效检查点恢复，拒绝旧执行者提交。首次截止时间、已用预算和调用计数 MUST 保留；恢复与重试 MUST 有限，不能承诺外部付费调用恰好一次。

#### Scenario: Old worker returns after lease expiry
- **WHEN** 旧执行者失去租约后仍尝试写入阶段或成功结果
- **THEN** 提交被拒绝，不覆盖当前执行者状态

#### Scenario: Retry after budget exhaustion
- **WHEN** 任务已耗尽调用预算或超过原截止时间
- **THEN** 恢复不会重置预算重新调用，用户获得明确失败或重新发起操作的说明

### Requirement: Cancellation and deletion prevent late publication

The system SHALL 支持显式取消，并在付费步骤及最终发布前复核取消、账号与资料状态。页面关闭 MUST NOT 自动取消任务；取消或删除生效后 MUST NOT 发布新的学习结果或恢复已删资料。

#### Scenario: User cancels while an external request is in flight
- **WHEN** 用户取消成功后外部响应才返回
- **THEN** 返回结果不再发布为新关卡或可用索引，实际已发生调用仍计量

#### Scenario: User merely switches to another app
- **WHEN** 用户未点取消而使小程序进入后台
- **THEN** 任务继续，回来可查询最终状态

### Requirement: Shared model limits and separate embedding usage

The system SHALL 对实际模型调用沿用账号每分钟 10 次及既有并发约束，所有重试计入用量。Embedding、问答和闯关 MUST 分别记录对应额度；排队等待 MUST 不无故占用旧核心操作的执行资格。

#### Scenario: Model call is retried after a timeout
- **WHEN** 本次调用与重试都已实际发出
- **THEN** 两次均计入模型调用限制，不因任务恢复抹去已用次数

#### Scenario: Only library indexing is requested
- **WHEN** 用户仅进行知识库向量化
- **THEN** 计入向量化用量，不新增答题记录或扣减闯关次数

### Requirement: Exclusive local index writer

The system SHALL 防止多个独立执行进程同时写入同一本地索引目录，执行服务不可用时 SHALL 明确返回或显示服务状态。既有核心接口 MUST 不因知识库执行服务停机而不可用。

#### Scenario: A second executor starts against the same local index
- **WHEN** 已有有效执行进程持有该本地索引
- **THEN** 第二进程无法同时获得写入资格，系统不产生竞争写入

#### Scenario: Executor is stopped
- **WHEN** 知识库执行器不可用
- **THEN** 知识库不伪造完成状态，旧主题出题和既有学习记录仍按原接口工作
