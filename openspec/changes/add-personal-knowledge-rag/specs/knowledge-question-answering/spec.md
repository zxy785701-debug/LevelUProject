# Spec Delta

## Purpose

提供用户可实际使用的知识库提问入口，基于本人选择的资料与获准网络证据生成有出处的回答，并保留可管理的问答历史及继续出题的学习衔接。

## ADDED Requirements

### Requirement: Explicit question scope and asynchronous answers

The system SHALL 允许用户选择一份或多份就绪资料，或明确选择本账号全部就绪资料，输入问题并提交后台问答任务。未声明范围或空选择 MUST NOT 隐式扩大范围，首版问答 MUST 不偷偷携带此前问答上下文。

#### Scenario: Ask across multiple documents
- **WHEN** 用户选择两份本人就绪资料并提交问题
- **THEN** 系统返回任务，完成后展示该范围内的回答及获准联网补充的实际来源

#### Scenario: Empty selection is submitted
- **WHEN** 用户未选资料且未显式选择全部
- **THEN** 请求获得范围校验提示，不自动检索全部资料或其他账号内容

#### Scenario: Previous question contains unrelated private content
- **WHEN** 用户开始一个新的单轮问题
- **THEN** 上一次回答与资料内容不自动进入新问题上下文

### Requirement: Supported answers and navigable citations

The system SHALL 对回答中的事实性陈述绑定可核验的真实证据，展示资料标题、页码或片段位置及网页时间信息，并在发布前检查引用存在性与支持关系。无依据事实 MUST 不以确定结论发布。

#### Scenario: A supported answer is published
- **WHEN** 已登记片段支持回答中的结论
- **THEN** 用户可从对应引用打开实际来源片段并看到来源定位

#### Scenario: Model invents a citation identifier
- **WHEN** 回答使用未登记或不属于当前任务的引用
- **THEN** 回答不能以已核实结果发布，必须修正或明确失败

### Requirement: Insufficient and conflicting evidence is visible

The system SHALL 在证据不足时说明尚不能回答的部分，并可提示补充资料或缩小问题。相互冲突的来源 MUST 分别说明，不假称取得唯一确定结论；联网未完成 MUST 不标为最新核实。

#### Scenario: No source supports the requested private fact
- **WHEN** 所选资料不含该事实且没有获准的可靠补充
- **THEN** 系统展示资料不足，不靠模型已有知识编造私有文件观点

#### Scenario: Selected sources disagree
- **WHEN** 两份相关资料给出冲突说法
- **THEN** 回答分别引用并指出冲突，不能无依据地隐去其中一方

### Requirement: Owned question history is manageable

The system SHALL 保存本账号单次问答及必要引用快照，支持列表、详情和删除。跨账号访问 MUST 被拒绝；资料删除后历史按其生命周期可读并标明原资料已删除，删除历史后 MUST 不再出现在本人查询中。

#### Scenario: Delete a saved question
- **WHEN** 用户删除本账号的一条问答历史
- **THEN** 列表和详情不再返回该记录，不影响其他问答或既有关卡

#### Scenario: Source document is removed later
- **WHEN** 用户查看引用资料已被删除的既有问答
- **THEN** 可见必要快照与删除提示，但该资料不能被再次检索为新证据

### Requirement: Question to quiz preserves original evidence intent

The system SHALL 允许从问答进入出题，将原始问题与原资料范围作为学习目标重新准备并由用户确认。AI 回答本身 MUST NOT 当作原始证据，未确认范围 MUST 不直接发布关卡。

#### Scenario: Create a quiz from a question
- **WHEN** 用户点击“按这个问题出题”
- **THEN** 系统基于原始问题、当前有效资料与联网权限准备多选主题，确认后才进入生成

#### Scenario: The answer cites a source no longer available
- **WHEN** 转出题时原资料已删除或版本已变化
- **THEN** 要求刷新范围或调整资料，不用旧回答文字替代已失效原始依据

### Requirement: Q and A usage is separate from quiz rewards

The system SHALL 为问答设置独立额度并计入实际模型调用限制，问答 MUST NOT 创建答题尝试、经验、错题或闯关报告，也不得扣减闯关次数。

#### Scenario: Complete a knowledge question
- **WHEN** 用户获得一份知识库回答而未生成关卡
- **THEN** 仅记录问答及对应调用用量，闯关奖励与题目作答统计保持不变
