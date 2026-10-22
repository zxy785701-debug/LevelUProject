# Spec Delta

## Purpose

使学习 Agent 能根据用户目标从本人知识库、公开网络或两者取得真实依据，同时将资料范围、联网权限、预算和来源可靠性保持在服务端可验证的边界内。

## ADDED Requirements

### Requirement: Authorized adaptive retrieval routes

The system SHALL 允许 Agent 根据目标选择知识库检索、联网或组合，且只能访问当前账号明确范围内的就绪资料。明确要求根据所选资料时 MUST 先检索该范围，公网结果 MUST NOT 冒充私有资料内容。

#### Scenario: A document-specific question is submitted
- **WHEN** 用户询问“根据这些资料，作者为什么这样做”
- **THEN** 系统检索所选资料，对作者观点的陈述使用该资料的真实支持片段

#### Scenario: The goal is a general recent development
- **WHEN** 用户允许联网且提出不强制依赖私有资料的时效问题
- **THEN** Agent 可选择联网或混合路线，结果说明实际来源，不能虚报已检索或已读资料

#### Scenario: Agent attempts to widen document access
- **WHEN** 模型调用工具时指定未授权文档或另一账号范围
- **THEN** 服务端拒绝扩大范围，不返回越权片段

### Requirement: Explicit web permission in knowledge workflows

The system SHALL 对新知识库问答与出题默认允许自动联网补充，并允许用户关闭。关闭时 MUST 不执行联网工具，工具调用本身仍须服务端校验；旧入口的联网默认规则 MUST 保留。

#### Scenario: New knowledge request omits the switch
- **WHEN** 用户从知识库进入问答且未显式设置联网字段
- **THEN** 系统按默认允许联网处理，并在界面展示该状态

#### Scenario: Web access is disabled
- **WHEN** 用户关闭联网后模型仍尝试执行联网工具
- **THEN** 系统不向搜索或网页服务发出请求，只能使用获准知识库依据

### Requirement: Dynamic keyword and URL retrieval

The system SHALL 同时支持关键词搜索和已知公开网址提取，并根据复杂度、覆盖缺口和预算动态选择摘要或正文及结果数。国家偏向 SHALL 使用受支持能力，城市 SHALL 用关键词与地域核对处理，不宣称不存在的城市筛选。

#### Scenario: User supplies a public URL
- **WHEN** 目标是读取指定网页内容
- **THEN** Agent 可以直接提取该网址的实际正文，不必先进行无关关键词搜索

#### Scenario: Local information is requested
- **WHEN** 用户明确要求某城市的知识或背景
- **THEN** 系统在查询中体现城市并核对结果地域，必要时使用国家偏向，不从界面语言推定用户所在地

#### Scenario: Complex and simple topics differ
- **WHEN** 简单事实与复杂技术目标需要不同证据深度
- **THEN** 工具参数可分别选择摘要或正文以及不同数量结果，均受服务端预算限制

### Requirement: Original content and bounded evidence

The system SHALL 登记实际返回的知识库片段与网络内容，保留定位、获取时间及截断状态，并控制片段数量和总上下文。模型摘要、相似度或模型生成的 URL MUST NOT 代替真实证据或事实支持校验。

#### Scenario: An old page snapshot is retrieved from the library
- **WHEN** 引用来自此前入库的网页
- **THEN** 来源显示实际抓取时间，不把本次本地检索描述为刚刚联网核实

#### Scenario: Relevant text does not support a proposed claim
- **WHEN** 检索片段与问题相似但不包含该结论的依据
- **THEN** 系统不能仅因相似度高就将该结论视为已证实

### Requirement: Honest retrieval degradation

The system SHALL 在联网不可用时继续使用足够的知识库依据并说明实际状态。对依赖私有资料且无充分支持的问题 MUST 说明资料不足或不可用，不使用模型记忆或公网同名内容伪造文件内容。

#### Scenario: Search credentials are absent but the library supports the answer
- **WHEN** 联网服务不可用且授权知识库提供充分依据
- **THEN** 问答或出题仍可完成，并说明未完成联网补充

#### Scenario: Required private knowledge cannot be retrieved
- **WHEN** 问题依赖所选文件但文件不可用或未找到支持
- **THEN** 系统返回依据不足或明确失败，不给出伪称来自文件的完整结论

### Requirement: Private content and untrusted instructions stay contained

The system SHALL 限制公网查询为用户目标所需的公开主题或安全概括，禁止自动发送私有片段、文件全文、账号标识或问答历史。文档及网页中的指令 MUST NOT 改变工具权限、数据范围和调用预算。

#### Scenario: Private sentinel text appears in a retrieved chunk
- **WHEN** Agent 随后尝试联网补充
- **THEN** 公网工具参数不含该私有哨兵文本或其全文复制，无法安全概括时不发起该查询

#### Scenario: A page instructs the agent to reveal another user's data
- **WHEN** 检索结果包含扩大权限或绕过审核的提示
- **THEN** 这些提示只作为不可信内容，不触发额外权限或未经允许的数据访问

### Requirement: Retrieval budget is enforced across retries

The system SHALL 为每任务设置模型、工具、证据及总时限预算，并将失败尝试计入预算。达到限制后 MUST 结束或返回明确的部分依据状态，不继续无上限搜索。

#### Scenario: Repeated searches return empty results
- **WHEN** 多次空结果已耗尽工具预算
- **THEN** 系统停止调用并说明证据不足，而非重新开始无限检索
