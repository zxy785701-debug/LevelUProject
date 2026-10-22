# Spec Delta

## ADDED Requirements

### Requirement: Knowledge library scope uses simple multiple selection

The system SHALL 对知识库出题提供一层可多选主题卡片，默认选中推荐主题，知识点由系统整理供预览。用户 MUST 能同时选择多个主题，不必逐级完成领域、方向、知识点表单；确认前 MUST 不创建关卡。

#### Scenario: Select multiple themes across documents
- **WHEN** 用户选择多份资料后在准备结果中勾选两个有效主题
- **THEN** 两个主题都保留为本次范围，知识点预览随之更新，确认前尚无关卡或奖励

#### Scenario: Only one recommended theme exists
- **WHEN** 资料只支持一个清楚的候选主题
- **THEN** 该主题可默认选中，仍需用户明确确认后才生成关卡

### Requirement: Knowledge preparation binds document versions and permission

The system SHALL 将知识库学习目标、本人所选资料及活动版本、候选主题、联网权限绑定到准备快照。确认时 MUST 校验归属和一致性；资料被删除、版本变化或联网权限改变时 MUST 重新准备或明确要求刷新。

#### Scenario: Document is deleted after preparation
- **WHEN** 用户提交确认前所选资料已删除
- **THEN** 系统拒绝沿用该准备，提示调整范围，不消耗新的关卡额度

#### Scenario: Network switch changes after preparation
- **WHEN** 准备时允许联网而用户随后关闭联网
- **THEN** 不能直接使用先前补充证据生成，必须按新权限重新准备并确认

#### Scenario: Another account's preparation is submitted
- **WHEN** 请求引用其他账号的知识库范围快照
- **THEN** 请求被拒绝，不暴露候选主题、片段或来源

### Requirement: Knowledge scope preserves explicit multi-document boundaries

The system SHALL 围绕用户选定资料和主题整理范围，并显示实际可用依据与尚未覆盖部分。新知识库默认允许联网补充 MUST 对用户可见，旧主题与材料入口的范围确认及联网规则 MUST 保持原有行为。

#### Scenario: Requested theme is unsupported
- **WHEN** 选中资料和获准补充来源不足以支撑某主题
- **THEN** 系统说明不足并允许调整选择，不悄悄切换到其他领域或声称已覆盖整份长文

#### Scenario: Return to old material learning
- **WHEN** 用户改用原文档或网页直接出题入口
- **THEN** 该入口保留原有预览、确认和联网补充默认值，不被知识库默认开启规则覆盖
