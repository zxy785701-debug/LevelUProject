# quiz-generation-reliability Specification

## Purpose

让联网增强出题在外部服务失败、用户重复操作或中途离开时保持可理解、可恢复的行为，并持续保留自动降级与来源状态，避免用户把模型已有知识生成的题目误认为经过最新网络资料核实。

## Requirements

### Requirement: Search failure automatically falls back transparently
系统 SHALL 在检索未配置、超时、服务限流、服务额度不足、无可读结果或资料不足且存在明确学习主题或可用材料时自动降级，不额外要求用户批准降级；仍 SHALL 遵守每次范围确认，并显示“未联网核实”及原因。仅网址且页面不可读时 MUST 提示补充学习内容，不猜测页面。

#### Scenario: Search timeout before generation
- **WHEN** 用户已确认范围但补充检索超时
- **THEN** 系统使用当前可用材料及模型知识继续出题，保留原定范围，成功结果标注“未联网核实”，不声称完成最新事实核实

#### Scenario: Search is not configured
- **WHEN** 后端缺少检索凭证但模型服务可用
- **THEN** 用户仍可完成范围确认并生成明确标注“未联网核实”的关卡，界面不显示虚假的联网成功步骤

#### Scenario: Material supplementation fails
- **WHEN** 材料出题已开启联网补充而检索失败
- **THEN** 系统优先依据所选原材料继续，显示“联网补充失败，未联网核实”，保留原材料引用；不能用无关模型知识替换材料范围

### Requirement: Fallback preserves normal validity and failure rules
降级题库 MUST 通过题型、题量、答案一致性和内容安全校验，MUST NOT 伪造来源或最新事实。身份失效、用户额度限制、用户取消、模型不可用、结构不合法及已知事实矛盾 MUST 按相应失败规则处理，不能通过降级绕过。

#### Scenario: Insufficient evidence is not the same as contradiction
- **WHEN** 引用不足以核实一组结构有效且无已知矛盾的题目
- **THEN** 可以以未核实状态返回，并移除不支持其结论的引用；若已知答案错误则不得返回该错误答案

#### Scenario: Model cannot produce a valid quiz
- **WHEN** 搜索已降级，模型也持续返回无效结构或无法形成可回答的问题
- **THEN** 系统返回生成失败并保留用户输入，不制造虚假题库以保证成功率

### Requirement: Provenance status persists through learning history
系统 SHALL 保存范围、来源状态、检索时间及降级原因；题库、逐题反馈、复盘、历史重闯和错题复习 MUST 保留这些信息，历史数据缺少标识时 MUST NOT 默认视为已联网核实。

#### Scenario: Unverified quiz is resumed
- **WHEN** 用户重新登录后恢复、重闯或复盘降级生成的关卡
- **THEN** “未联网核实”标识仍在，不能因缓存或报告重新生成而消失

#### Scenario: Wrong questions combine different origins
- **WHEN** 错题复习同时包含有来源支持和未核实的题目
- **THEN** 每题保留原有来源状态，集合不能统一误标为已核实，也不能引用其他原题的来源

#### Scenario: Legacy quiz has no provenance
- **WHEN** 用户打开本次上线前生成且没有来源状态的关卡
- **THEN** 关卡仍可答题与复盘，显示既有材料信息或“历史题目未记录联网核实状态”

### Requirement: Preparation can be observed cancelled and expired
系统 SHALL 提供真实准备进度和终态，允许取消并保留输入；取消、过期或账号已删除的准备任务 MUST NOT 在迟到结果返回后变为可生成状态。后台中断 MUST 最终转为可重试的明确状态。

#### Scenario: User cancels preparation
- **WHEN** 用户在检索或整理范围时取消
- **THEN** 停止启动后续调用，迟到结果不得覆盖取消状态，也不创建关卡

#### Scenario: Process restarts during preparation
- **WHEN** 后端在准备过程中中断且未完成记录
- **THEN** 用户查询时获得已过期或中断的状态，并能以新操作重试，不会永久停留在加载中

### Requirement: Retry and recovery do not duplicate work
系统 SHALL 按账号与操作标识绑定输入和确认范围；相同操作重试不得重复启动外部调用、重复创建关卡或重复扣费额度，参数变化 MUST 被识别为不同操作或冲突。

#### Scenario: Client loses the response
- **WHEN** 生成已完成但客户端断网，随后查询或重试相同操作
- **THEN** 返回原有结果，不重复生成；仍在执行时返回可查询状态

#### Scenario: Same operation key carries a different scope
- **WHEN** 调用方以相同操作标识提交不同领域或学习方向
- **THEN** 系统返回操作冲突，不复用旧范围结果

### Requirement: Work remains bounded and accounted for
系统 SHALL 对准备、检索及模型调用设置可配置的次数、时间和输入输出上限，沿用账号并发和实际模型调用限流；范围准备不得消耗新关卡额度，正式出题开始调用模型后按现有规则计一次新关卡额度。

#### Scenario: User previews several scopes
- **WHEN** 用户完成范围准备但未确认出题
- **THEN** 不扣新关卡额度；实际准备及模型调用按其独立限制记账，重复读取不重复计数

#### Scenario: Internal validation uses the model
- **WHEN** 出题后继续调用模型检查题目依据
- **THEN** 此调用同样受限流与操作期限约束，但不再扣第二次新关卡额度

### Requirement: Preparation and evidence are isolated by account
系统 MUST 对准备记录、来源快照与生成结果执行本人访问校验，检索凭证仅在后端使用。关键词搜索请求 SHALL 只携带本次主题或必要关键词，网页提取请求只携带本次允许读取的公开网址及必要参数，不附带账号资料、学习历史或上传材料全文；未使用准备记录 SHALL 有限期清理，账号注销时删除关联记录。

#### Scenario: Foreign preparation is requested
- **WHEN** 一个账号查询或取消另一个账号的准备记录
- **THEN** 系统拒绝操作且不泄露记录是否存在或其中内容

#### Scenario: User removes the account
- **WHEN** 用户完成现有注销流程
- **THEN** 新增准备记录和来源快照随其学习记录删除，不能被后台迟到结果重新写入

### Requirement: Retrieval and generation expose truthful background progress
系统 SHALL 让范围准备和新主题生成以可查询的后台操作执行，立即返回操作标识并展示真实阶段、等待原因和终态；MUST NOT 要求客户端维持覆盖整个任务期限的单个网络请求，也不得把离开页面描述为已取消后台生成。

#### Scenario: Agent takes multiple retrieval steps
- **WHEN** AI 在搜索、提取及范围整理之间执行多次调用
- **THEN** 用户可查询当前真实阶段，不显示虚假的固定进度或在尚未出题时声称题库已完成

#### Scenario: Generation continues after leaving the page
- **WHEN** 用户已确认主题并提交生成，随后离开或断网
- **THEN** 后台操作在有效期限内继续，用户通过原操作恢复阶段或原有 Session，不启动第二次生成

#### Scenario: Process stops during generation
- **WHEN** 后台生成因进程中断无法继续
- **THEN** 系统最终显示中断或过期状态并允许新操作重试，不永久停在运行中，也不宣称已自动续跑

### Requirement: Agent calls share enforceable resource limits
系统 SHALL 对每阶段的模型请求、工具尝试、结果条数、提取页面数、内容体积和总时长设置硬上限，所有规划、继续判断和重试均计入；MUST NOT 将整个 Agent 运行只记作一次模型请求或允许并行工具绕过上限。

#### Scenario: A tool batch exceeds the remaining limit
- **WHEN** AI 同时请求多个工具调用且超过剩余次数
- **THEN** 系统逐项检查并阻止超出部分，不先发起全部付费请求再事后记录超限

#### Scenario: Full content threatens context limits
- **WHEN** 搜索或提取返回大量正文
- **THEN** 系统限制保存及累计入模体积，记录截断和未覆盖内容，不因工具返回全文而取消预算

#### Scenario: Retrieval uses up its allowance
- **WHEN** 检索工具达到阶段调用上限
- **THEN** 系统停止继续检索，依据已取得内容和正常降级规则决定后续，不无限循环或伪造已取得的来源

#### Scenario: Generation needs an independent review
- **WHEN** 检索后即将生成题目
- **THEN** 系统必须仍有出题与审核的模型预算；修正已知错误时必须同时预留再审核预算，不能因额度用完发布未经审核的修正题

#### Scenario: Agent requests an unapproved model or service
- **WHEN** 当前配置无法完成工具调用
- **THEN** 系统报告模型或配置问题，不静默更换服务商/模型，也不将普通模型猜测标成工具检索结果

### Requirement: Rate limit waits remain bounded and recoverable
系统 SHALL 保留账号实际模型请求限流；后台任务遇到暂时分钟额度不足时，在同一操作内展示等待及可计算时间，并在期限内继续。等待、重试和恢复 MUST 不重复计关卡额度、不重跑已完成检索，亦不得绕过账号并发限制。

#### Scenario: Model quota becomes temporarily unavailable
- **WHEN** 后台任务即将调用模型，但当前滚动窗口的调用额度不足且期限允许等待
- **THEN** 阶段显示等待额度，达到可调用时间后重新检查并继续，等待期间不额外发起模型请求

#### Scenario: Remaining deadline cannot accommodate waiting
- **WHEN** 限流等待会使任务无法在总期限内完成必要步骤
- **THEN** 系统返回明确超时或限流终态，保留用户输入及已记账结果，不以自动降级绕过额度

#### Scenario: Account is removed while waiting
- **WHEN** 账号在任务等待时完成注销
- **THEN** 任务停止后续模型和工具调用，迟到结果不能重新写入已删除账号

### Requirement: Background execution preserves explicit material compatibility
系统 SHALL 明确区分后台操作响应和已完成 Session；新主题生成返回操作，材料请求支持显式选择后台执行并保留旧同步契约。客户端 MUST 按所选模式解析结果，不把运行中的操作当作可答题关卡。

#### Scenario: Updated material client requests background execution
- **WHEN** 材料客户端显式请求后台生成
- **THEN** 系统返回可查询操作，最终仍取得相同学习语义的 Session，并保留所选知识点和补充开关

#### Scenario: Legacy material client uses synchronous execution
- **WHEN** 材料请求未选择后台模式
- **THEN** 系统按既有同步契约返回 Session 或标准业务错误，在同步期限内结束，不改成未声明的操作对象
