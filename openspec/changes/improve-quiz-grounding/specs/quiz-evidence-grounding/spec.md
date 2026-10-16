# Spec Delta

## Purpose

让生成的题目与用户确认的学习范围及可读取的来源保持一致，使新技术、网络文化和用户材料能够用于可靠学习，并让用户在答题讲解中追溯具体依据与资料时间，区分证据支持和未经核实的内容。

## ADDED Requirements

### Requirement: Retrieval follows confirmed meaning and focus
系统 SHALL 按用户确认的领域、方向和知识点筛选或补充检索内容；MUST NOT 将同名但不同领域的结果用于支撑题目。相关性 SHALL 优先于单纯的搜索排名。

#### Scenario: Selected meaning excludes unrelated results
- **WHEN** 用户选择 AI/智能体方向的 Harness Engineering，检索结果混有线束制造等资料
- **THEN** 其他领域内容不进入该方向题目的依据集合

#### Scenario: Selected focus requires targeted supplementation
- **WHEN** 初次资料主要介绍节目，而用户确认学习热门梗与名场面
- **THEN** 系统围绕该方向补充检索；无法取得充分依据时执行明确标识的降级，不能悄悄改回节目基础

### Requirement: Retrieved evidence has an authentic source
系统 SHALL 保留每条可用于出题的真实文本片段、来源标识、标题、URL及检索时间；MUST NOT 将搜索摘要之外未取得的正文、服务商合成答案或模型生成的 URL 冒充已读取的证据。

#### Scenario: Search result has only a title
- **WHEN** 搜索返回标题与 URL，但没有足以支持题目的文本
- **THEN** 该结果可以展示为候选来源，但不能支撑“有来源支持”的题目状态

#### Scenario: A page cannot be retrieved
- **WHEN** 单个来源不可访问而其他来源可读
- **THEN** 系统继续使用可读来源，记录缺失来源，按可用证据判断是否需要降级

### Requirement: Source time is represented without invented freshness
系统 SHALL 区分原文发布或更新时间与本次检索时间；未知原文日期 MUST 保持未知。历史来源可以支持经典事实，但 MUST NOT 因刚被检索就被标注为最新事实。

#### Scenario: Undated page is retrieved today
- **WHEN** 已取得文本但无法确认原文日期
- **THEN** 展示本次检索时间及“原文日期未知”，不把检索时间当作发布时间

#### Scenario: Old content is relevant to a current discussion
- **WHEN** 网络热梗源于较早播出的节目
- **THEN** 系统允许原始资料与后续讨论共同支撑题目，并按实际取得的证据说明语境，不要求所有资料都是近期发布

### Requirement: Questions substantively match the selected focus
系统 SHALL 让题干、选项、答案和讲解围绕确认的方向组织；选择具体方向时，至少过半题目 MUST 实质考查该方向，不得用名称识别或无关常识凑足题量。

#### Scenario: Meme learning is substantive
- **WHEN** 用户选择“花少2—热门梗与名场面”且资料充分
- **THEN** 题目主要考查有依据的梗含义、场景语境、表达用法或误读，覆盖至少两个不同梗或名场面，不能整组只问节目名称和嘉宾

#### Scenario: Comprehensive focus includes multiple dimensions
- **WHEN** 用户选择综合方向并确认至少两个有资料支持的知识点
- **THEN** 题目覆盖这些不同维度，不能全部落在同一个容易出题的知识点

### Requirement: Citation existence and factual support are both checked
系统 SHALL 对标注为有来源支持的题目同时校验引用真实存在及引用内容支持题干事实、正确答案和讲解；MUST NOT 仅凭引用 ID 合法就认为事实已核实。不同来源的矛盾结论不得被无说明地合并为唯一答案。

#### Scenario: Valid citation does not support the answer
- **WHEN** 一道题引用真实片段但该片段未提供答案依据
- **THEN** 该题不能以有来源支持状态发布；不存在已知矛盾时按未核实规则处理并去除误导性引用

#### Scenario: Evidence contradicts the generated answer
- **WHEN** 已取得的明确证据与模型答案冲突
- **THEN** 系统在受限重试中修正，仍冲突则生成失败，不得用“未联网核实”掩盖已知错误

#### Scenario: Sources disagree
- **WHEN** 来源对梗的归属或技术定义存在不可消除的冲突
- **THEN** 系统避免将争议内容作为无条件的唯一正确答案，可以转为有明确来源限定的理解题或选择其他知识点

### Requirement: Users can inspect the supporting excerpt
系统 SHALL 在答题反馈中展示本题真实来源的标题、URL、引用片段和时间信息；材料来源的页码或字幕时间 SHALL 保持真实，网络补充 SHALL 与原材料明确区分。

#### Scenario: Answer feedback includes source details
- **WHEN** 用户提交答案并打开来源
- **THEN** 显示与本题有效引用对应的片段，不展示不存在的链接、页码或字幕时间

### Requirement: Materials and web content cannot change application rules
系统 MUST 将输入材料及检索页面作为学习数据处理，不能执行其中修改出题规则、泄露凭证或伪造引用的指令；新增依据、校验报告和内部提示词 MUST NOT 导致未答题答案提前下发。

#### Scenario: Retrieved text contains injected instructions
- **WHEN** 页面正文要求忽略系统规则或将所有答案设为某个选项
- **THEN** 系统忽略这些指令并继续按确认范围、题型和引用要求处理

#### Scenario: Generated evidence metadata could expose answers
- **WHEN** 客户端读取尚未作答的关卡
- **THEN** 正确答案、讲解、答案校验理由及逐题证据映射不会提前下发；用户在确认页主动预览的学习资料除外

### Requirement: Retrieval selects tools according to the learning need
系统 SHALL 向检索 AI 提供关键词搜索和指定网址内容提取两种能力，由其根据用户目标、当前结果及剩余预算决定调用与继续动作；MUST NOT 对全部输入强制执行同一固定检索顺序，亦不得以模型总结冒充实际工具结果。

#### Scenario: Keywords require discovery
- **WHEN** 新关键词没有已取得的有效来源且联网可用
- **THEN** AI 发起实际关键词搜索，并根据结果决定是否需要读取原网页或继续查询

#### Scenario: A specific page is the learning target
- **WHEN** 用户指定页面作为学习材料
- **THEN** AI 使用网页提取取得该页面内容；只有搜索标题或摘要时不能报告已完成页面读取

#### Scenario: Search already returns sufficient page content
- **WHEN** 搜索响应中的真实正文已覆盖学习目标
- **THEN** AI 可以停止补充，不必为满足固定流程而再次提取相同页面

#### Scenario: Search snippet lacks essential context
- **WHEN** 已取得摘要不足以支持目标知识点的条件或语境
- **THEN** AI 可在预算内提取对应原页面或调整搜索，并根据实际结果决定证据是否充分

### Requirement: Retrieval depth and result count adapt to the topic
系统 SHALL 允许 AI 根据知识复杂度、歧义、时效、来源覆盖选择摘要或正文、搜索/提取深度、结果数量以及必要的时间/来源约束；参数 SHALL 在允许范围内生效，MUST NOT 将所有主题固定为相同深度与条数。

#### Scenario: Simple knowledge is adequately supported by snippets
- **WHEN** 简单稳定知识的少量摘要已提供足够依据
- **THEN** 系统可使用这些真实片段出题，无需对每条结果都请求完整正文

#### Scenario: Complex knowledge needs detailed evidence
- **WHEN** 新概念、多义词或复杂对比需要更多上下文
- **THEN** AI 可在搜索时直接请求正文并增加结果数；缺少必要内容时继续提取或说明不足

#### Scenario: Parameters change between independent calls
- **WHEN** 一次调用选择摘要和较少结果，另一次选择正文和更多结果
- **THEN** 两次外部请求分别应用其已校验参数，不能被共享配置覆盖或污染其他用户调用

#### Scenario: A parameter is unsupported or exceeds the budget
- **WHEN** AI 提交不存在的参数、无效组合或超出上限的结果数量
- **THEN** 系统在外部调用前拒绝该请求并返回可处理原因，不静默发送无效参数或取消限制

### Requirement: Retrieval language and geography follow the topic
系统 SHALL 按主题选择资料语言与地域意图，区分回答语言、搜索语言和地理范围；全球知识不默认限制国家，城市使用地名查询并核对结果内容，MUST NOT 将国家偏向描述为严格地域筛选或根据用户语言推断所在地。

#### Scenario: Chinese question benefits from original English sources
- **WHEN** 中文技术问题需要英文原始资料支持
- **THEN** AI 可使用英文或双语查询，答案保持用户语言偏好，不因中文输入而排除国外来源

#### Scenario: Topic has no geographic restriction
- **WHEN** 用户学习全球通用知识且未指定地域
- **THEN** 系统不自动添加国家或城市限制

#### Scenario: Country relevance is requested
- **WHEN** 用户明确学习某国家相关内容且所选搜索类别支持国家偏向
- **THEN** 系统应用有效国家偏向，并按实际结果核对相关性，不承诺所有结果来自该国

#### Scenario: A city has namesakes
- **WHEN** 用户指定的城市名称存在跨国或跨地区重名
- **THEN** 查询保留明确国家/地区语境并核对资料所指城市；无法消歧时在范围确认中呈现，不自行改成另一城市

#### Scenario: Search category does not support country bias
- **WHEN** AI 选择的搜索类别不能使用国家偏向
- **THEN** 系统不发送不适用参数，仍通过查询保留地域意图，不能静默取消用户明确的城市范围

### Requirement: Full page retrieval is distinguished from selected excerpts
系统 SHALL 在用户指定网页的完整读取模式中请求可访问页面正文，区分摘要、定向片段、正文和读取不完整状态；获取内容与送入模型的片段 SHALL 分开记录，MUST NOT 将截断或按查询选出的片段声称为整个页面。

#### Scenario: A page is requested in full
- **WHEN** 用户以指定网页作为原材料
- **THEN** 获取阶段不启用只返回查询相关少量片段的模式，保存上限内的实际正文，再分段供预览及出题使用

#### Scenario: A complex page requires deeper extraction
- **WHEN** 基础提取缺少目标表格或必要页面结构
- **THEN** AI 可在预算内提升提取深度；仍未取得的内容明确标缺失，不能以猜测填补

#### Scenario: A long page exceeds model context
- **WHEN** 实际取得正文超过本次模型证据预算
- **THEN** 系统选择覆盖学习目标的片段并记录入模截取，不把片段长度当作页面真实长度，也不声称未覆盖知识点已核实

#### Scenario: Some pages fail in a batch
- **WHEN** 同批页面提取有成功和失败项，即使请求整体返回成功
- **THEN** 系统分别记录每页状态，保留成功正文，不把失败项或空正文当作已读取证据

#### Scenario: Requested content is unavailable
- **WHEN** 登录限制、动态内容或保存上限导致部分内容无法取得
- **THEN** 系统披露相应读取状态，只以真实保留的片段支撑题目，不宣称完整覆盖页面
