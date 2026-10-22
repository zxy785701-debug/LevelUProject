# Spec Delta

## ADDED Requirements

### Requirement: Knowledge quizzes preserve multi-document provenance

The system SHALL 为知识库题目保存所引用文档、版本、片段及真实定位的快照，并区分原资料与联网补充。模型 MUST 只引用当前任务已登记的片段，来源属性 MUST 由程序从实际证据填写。

#### Scenario: A question draws on two uploaded files
- **WHEN** 一道题的正确答案与讲解需要两份资料共同支持
- **THEN** 引用分别对应两份资料的有效片段及各自版本和位置，不合并成一个虚构来源

#### Scenario: Imported webpage supports a question
- **WHEN** 题目使用此前入库网页的片段
- **THEN** 保留原网址、实际抓取时间和可用正文位置，不将本次知识库查询时间标为网页更新时间

#### Scenario: Supplement supports an additional fact
- **WHEN** 允许联网且题目实际使用本次取得的网络补充
- **THEN** 补充引用与知识库原资料分开展示，来源状态按真实支持关系计算

### Requirement: Knowledge quizzes require supported facts before release

The system SHALL 对知识库出题执行引用存在性及事实支持的独立审核，校验题干关键事实、答案与讲解。明确依赖私有资料而缺乏支持时 MUST 修正或失败，不得以“未联网核实”掩盖编造的文档内容。

#### Scenario: Private fact is only in model memory
- **WHEN** 草稿答案未得到选定资料或获准补充证据支持
- **THEN** 系统不能发布为知识库关卡，受限修正后仍不足则提示调整资料或范围

#### Scenario: Documents disagree on the tested fact
- **WHEN** 不同资料对同一事实给出矛盾说法
- **THEN** 系统使用有明确来源限定的题目或更换知识点，不给出无条件唯一答案

#### Scenario: Legacy topic uses permitted fallback
- **WHEN** 用户通过既有一般主题入口进行出题且满足原降级规则
- **THEN** 原“未联网核实”降级仍按旧契约工作，不被知识库的严格资料规则全局关闭

### Requirement: Knowledge source reading respects answer visibility

The system SHALL 在提交答案后的反馈中提供对应知识库引用定位和必要快照；原资料删除后 SHALL 显示删除状态。新增多文档元数据 MUST NOT 将未答题的正确答案、讲解或逐题证据映射提前下发。

#### Scenario: Session is opened before answering
- **WHEN** 客户端读取尚未提交答案的知识库关卡
- **THEN** 仍按既有隐藏规则获取题目，不能通过新增引用字段获取答案或讲解

#### Scenario: Source is deleted after a quiz was completed
- **WHEN** 用户在既有报告中打开相应引用
- **THEN** 能查看历史必要片段与原定位，并看到原资料已删除，不把资料恢复到知识库
