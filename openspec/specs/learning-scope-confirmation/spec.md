# learning-scope-confirmation Specification

## Purpose

让用户在主题生成题目前明确确认想学的含义、领域和内容方向，利用检索结果减少新词误解、同名歧义及学习重点错位，同时在无法检索时保留透明且可调整的范围确认流程。

## Requirements

### Requirement: Keyword topics are searched before scope confirmation
系统 SHALL 对首页新提交的关键词主题默认尝试联网检索，随后呈现可确认的学习范围；检索失败时进入带原因标识的降级范围准备，MUST NOT 静默跳过范围确认直接创建关卡。

#### Scenario: New topic has readable search results
- **WHEN** 用户提交一个有效学习主题且检索返回可读内容
- **THEN** 系统展示主题含义、领域、可选学习方向、知识点和来源概要，并等待用户确认
- **AND** 此时尚未创建题库、答题轮次或奖励

#### Scenario: Search fails before confirmation
- **WHEN** 联网服务超时或未配置
- **THEN** 系统自动准备候选学习范围，明确显示“未联网核实”及原因，仍由用户确认范围

### Requirement: Ambiguous meanings remain selectable
系统 SHALL 区分同名主题的不同领域，展示其简短说明并让用户选择；MUST NOT 将模型的猜测当作检索结论，也 MUST NOT 在用户选择后自动切换领域。

#### Scenario: Harness Engineering has multiple meanings
- **WHEN** 输入 Harness Engineering，检索资料同时涉及 AI/智能体工程和其他领域
- **THEN** 确认页面分别展示相应含义；用户选择 AI/智能体工程后，后续检索与题目仅围绕该选择展开

#### Scenario: Intended meaning is missing
- **WHEN** 候选含义都不符合用户意图
- **THEN** 用户可以改写主题或补充领域说明并重新准备范围，不必选一个错误候选继续

### Requirement: Learning focus reflects the selected intent
系统 SHALL 提供适合当前主题的内容方向，包含知识点预览及其资料状态；方向 MUST NOT 仅由节目名、作品名或术语字面含义决定。用户 SHALL 能选择已有方向或改写主题重新准备。

#### Scenario: Entertainment topic includes cultural context
- **WHEN** 用户输入“花少2”且检索资料包含节目及相关网络文化信息
- **THEN** 范围选择包含“节目基础”“热门梗与名场面”“综合”等匹配资料的方向，并区分已取得资料与尚待核实的内容

#### Scenario: Technical topic exposes useful learning directions
- **WHEN** 技术主题的资料包含定义、应用及易混淆概念
- **THEN** 范围确认展示这些可学习内容，不局限于名称解释

### Requirement: Every new topic quiz requires explicit scope confirmation
系统 SHALL 在每次新主题出题前要求用户确认有效范围，即使仅有一个候选领域或使用降级模式；服务端 MUST 校验确认属于本人、当前主题与有效版本。

#### Scenario: One obvious meaning still needs confirmation
- **WHEN** 主题仅有一个清楚的候选含义
- **THEN** 系统展示该范围，只有用户点击确认后才启动出题

#### Scenario: Legacy client bypasses preparation
- **WHEN** 调用方仅提交文本而未提供有效范围确认
- **THEN** 系统返回需要确认学习范围的明确错误，不直接出题也不扣新关卡额度

#### Scenario: Changed or foreign preparation is submitted
- **WHEN** 请求引用其他账号的准备记录，或引用与当前主题、版本不一致的范围
- **THEN** 系统拒绝出题且不消耗新关卡额度；不得泄露其他账号资料

### Requirement: Scope and question settings are bound to a generation
系统 SHALL 将确认的领域、方向、知识点、题量与难度绑定到本次生成；更改主题须重新准备，更改选择须重新确认。MUST NOT 将旧请求的结果套用到新选择。

#### Scenario: User changes selection during retry
- **WHEN** 用户从节目基础改为热门梗并重新确认
- **THEN** 新生成使用新选择，旧请求仅可恢复其原有结果，不得覆盖新选择

### Requirement: Material input preserves its explicit boundary
系统 SHALL 保留文档、网页和视频的材料预览、范围确认及联网补充选择。关闭补充时 MUST 只依据所选材料出题，不得通过新主题检索流程暗中扩展材料范围。

#### Scenario: Material-only learning
- **WHEN** 用户选择材料知识点并关闭联网补充
- **THEN** 出题仅使用所选材料，界面显示“仅依据所选材料”，不会因主动关闭联网而误报搜索失败

#### Scenario: Material supplementation enabled
- **WHEN** 用户开启联网补充并确认材料范围
- **THEN** 补充检索围绕所选知识点展开，不能用整份材料中的其他主题替代用户选择

### Requirement: URL input prepares the specified page as learning material
系统 SHALL 同时支持关键词与 HTTP(S) 网址输入，网址可附学习说明；网址输入 SHALL 进入指定页面的材料准备并展示真实读取状态，MUST NOT 仅将网址作为关键词搜索就声称已经阅读网页。

#### Scenario: User submits a readable page URL
- **WHEN** 用户输入一个可读取的网页网址
- **THEN** 系统获取该页面正文，展示材料预览及可学习范围，并保留联网补充选择
- **AND** 用户确认前不创建关卡，后续范围以实际取得的页面内容为依据

#### Scenario: URL includes a learning instruction
- **WHEN** 用户同时提供网址和“重点学习其中的应用案例”等说明
- **THEN** 系统保留完整说明，在读取页面后围绕说明整理范围，不能丢弃网址或学习重点

#### Scenario: Only URL is provided and extraction fails
- **WHEN** 用户只提供网址且页面无法读取，不能确定可学习内容
- **THEN** 系统明确说明读取失败并提示补充主题或正文，不根据域名、路径或模型猜测伪造页面范围

#### Scenario: Unreadable URL accompanies a clear topic
- **WHEN** 页面读取失败但用户已明确给出学习主题
- **THEN** 系统可准备标注“未联网核实”的主题范围供确认，不把不可读页面列为已读依据

### Requirement: Page reading and web supplementation have distinct permissions
系统 SHALL 将读取用户指定网页与扩展搜索区分开；关闭材料联网补充时只允许取得指定材料，MUST NOT 通过自动工具调用搜索其他内容或跟随正文链接扩展学习范围。

#### Scenario: Supplementation is disabled for a page
- **WHEN** 用户指定网页并关闭联网补充
- **THEN** 系统仍读取该网页作为原材料，但不搜索其他网页、不提取正文中的外链作为额外材料

#### Scenario: Supplementation is enabled after selecting page content
- **WHEN** 用户选择页面中的知识点并开启联网补充
- **THEN** 补充资料只围绕所选内容展开，原网页与补充来源分别展示，不用整站或无关页面替换选择
