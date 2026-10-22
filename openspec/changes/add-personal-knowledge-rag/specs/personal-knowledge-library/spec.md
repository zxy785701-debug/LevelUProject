# Spec Delta

## Purpose

为每个账号提供主动积累文档与网页资料的私有知识库，使用户能够长期复用已解析的资料进行学习，并明确资料的处理状态、原始出处、版本和删除边界。

## ADDED Requirements

### Requirement: Explicit personal library import

The system SHALL 提供“我的知识库”，允许用户主动添加文字 PDF、DOCX、Markdown、TXT、单个公开网页或本账号已有可用材料。旧材料和联网检索结果 MUST NOT 自动入库，现有直接出题入口 MUST 保留。

#### Scenario: Add a Markdown document
- **WHEN** 用户主动上传受支持且未超限的 Markdown 文件
- **THEN** 系统返回资料与任务标识，显示处理中，成功后可用于问答与出题

#### Scenario: Existing material is not implicitly imported
- **WHEN** 用户继续使用旧网页或文档直接出题
- **THEN** 不自动新增知识库资料，旧入口及原联网默认规则保持有效

#### Scenario: Copy an owned material
- **WHEN** 用户明确将本账号已有可用材料加入知识库
- **THEN** 系统保存独立正文与出处，原临时材料清理后知识库资料仍可使用

### Requirement: Safe parsing and honest source positions

The system SHALL 校验文件、大小和公开网址安全，保留真实正文及可验证的页码、标题或段落位置。无法解析、扫描件、受限网址或未取得网页正文时 MUST 明确失败，不得用模型生成内容冒充原文。

#### Scenario: Public page import fails to obtain content
- **WHEN** 页面读取失败或只取得不能支持入库的空结果
- **THEN** 资料不进入就绪状态，用户可查看具体错误并重试或换资料

#### Scenario: References preserve actual positions
- **WHEN** 用户预览 PDF、DOCX 或 Markdown 片段
- **THEN** PDF 展示真实页码，其他格式展示实际标题或段落位置，不虚构分页

#### Scenario: Unsupported or unsafe input
- **WHEN** 输入超限、为扫描 PDF、恶意压缩文档或指向内网网址
- **THEN** 系统拒绝不支持的处理，返回可行动说明，不进行后续付费向量化

### Requirement: Persistent isolated library ownership

The system SHALL 按账号隔离列表、详情、原文、索引、任务和引用读取。知识库正文与来源信息 MUST 长期保存至用户删除，不采用临时材料的 24 小时清理规则；客户端 MUST NOT 扩大账号或索引访问范围。

#### Scenario: Old library document remains available
- **WHEN** 用户在超过 24 小时后再次访问未删除的就绪资料
- **THEN** 仍可预览并检索该资料，不要求重新上传

#### Scenario: Cross-account identifier is submitted
- **WHEN** 用户请求另一账号的资料、片段或任务标识
- **THEN** 请求被拒绝且不暴露该资料正文、向量位置或存在性信息

### Requirement: Validated atomic index publication

The system SHALL 仅在一份资料版本的分块与向量全部验证后将其用于检索。失败、取消和半成品 MUST 不可检索；重复任务 MUST 不重复发布，重建失败 MUST 保留此前可用版本。

#### Scenario: Indexing stops halfway
- **WHEN** 部分片段已完成向量化但后续批次失败
- **THEN** 新版本不能用于问答或出题，用户看到失败及重试入口

#### Scenario: Reindex fails after a successful import
- **WHEN** 已就绪资料的新索引版本重建失败
- **THEN** 旧活动版本仍可使用，不混合两个版本的片段

#### Scenario: Embedding configuration changes
- **WHEN** 模型、维度或距离配置改变
- **THEN** 系统建立独立索引版本并验证后切换，不在旧索引混入不兼容向量

### Requirement: Deletion immediately removes retrieval eligibility

The system SHALL 在资料删除成功返回时立即禁止其参与新检索和生成，并持久安排索引及原文件清理。账号注销 MUST 包含外部数据清理；必要的既有题目和问答引用快照按历史生命周期保留并标明原资料已删除。

#### Scenario: Query races with document deletion
- **WHEN** 用户删除一份资料后提交依赖该资料的新学习请求
- **THEN** 系统不再将其作为可用资料，要求更新范围或说明资料不可用

#### Scenario: Cleanup fails temporarily
- **WHEN** 删除向量或原文件时发生临时故障
- **THEN** 资料仍不可检索，清理任务可恢复重试，用户不会看到其重新出现

#### Scenario: Account deletion outlives relational records
- **WHEN** 账号关系数据已经删除但外部索引尚未清理
- **THEN** 清理指令仍可执行且不能恢复该账号资料的可检索状态

### Requirement: Library limits and cloud processing disclosure

The system SHALL 在导入前说明云端向量化与学习任务所需的数据处理，并提供服务端文件、资料总量、调用和用量限制。超限或配置不可用 MUST 给出明确提示，Embedding MUST 不扣除闯关次数。

#### Scenario: Import exceeds the account allowance
- **WHEN** 新导入将超过账号资料或向量化额度
- **THEN** 系统在新的付费调用前拒绝或暂停处理，说明限制与下一步操作

#### Scenario: Import without starting a quiz
- **WHEN** 用户完成资料入库但没有生成关卡
- **THEN** 闯关次数不因解析或向量化而减少
