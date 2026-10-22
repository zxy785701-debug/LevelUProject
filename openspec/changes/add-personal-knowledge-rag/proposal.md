# Proposal

## Why

现有文档和网页仅供单次材料出题，未提供长期私有资料管理、向量检索或知识库问答；长文复用还需要重新导入。新增个人 RAG 知识库，让用户主动积累资料，并在同一学习范围内进行问答或生成关卡，同时保持现有核心流程兼容。

## What Changes

- 新增“我的知识库”：主动上传文字 PDF、DOCX、Markdown，保留 TXT，并支持公开网页入库；支持列表、详情、预览、多资料选择、删除和失败重试。旧材料不自动迁入。
- 复用现有安全解析与 Tavily Extract，加入 LangChain 结构化分块、百炼 `text-embedding-v4` 和 Chroma 本地持久化；MySQL 保存正文、归属、版本和任务，知识库资料不套用临时材料的 24 小时清理规则。
- 新增受权限约束的 Agent 检索：知识库检索、官方 Tavily Search/Extract 可按目标组合；**新知识库流程默认允许自动联网补充**，用户可以关闭，旧文档/网页直接出题仍维持原开关规则。
- 新增有真实引用的知识库问答与问答历史；可将学习目标转为出题范围，但必须再次确认，不能将 AI 回答本身当作证据。
- 知识库出题复用题型校验、独立审核、服务端判分、奖励、历史、错题和报告；资料不足不凭模型记忆伪造私有资料内容。
- 为新增知识库能力提供 MySQL 持久任务与单独执行进程、短请求轮询、幂等、取消、租约恢复和索引清理。现有后台任务不在本次整体迁移。
- 所有新增后端功能按 TDD 交付；真实 MySQL 测试库、临时 Chroma 目录与受控外部服务边界共同验证，保存 RED/GREEN 证据并回归旧功能。

## Capabilities

### New Capabilities

- `personal-knowledge-library`: 私有资料的主动导入、解析分块、向量索引、长期保存、版本切换、删除及隔离。
- `durable-knowledge-tasks`: 新知识库任务的持久执行、轮询、预算、幂等、取消、中断恢复与单进程索引所有权。
- `agentic-knowledge-retrieval`: Agent 在知识库和联网工具间进行有权限、有边界、有预算的资料检索及证据登记。
- `knowledge-question-answering`: 用户可用的知识库问答、逐项引用、依据不足说明和账号隔离的问答历史。

### Modified Capabilities

- `learning-scope-confirmation`: 增加知识库学习范围确认，绑定所选资料、索引版本及默认开启的联网权限；不改变旧入口规则。
- `quiz-evidence-grounding`: 增加知识库片段和混合来源的可追溯快照、审核及资料不足处理。
- `quiz-generation-reliability`: 增加知识库出题与现有关卡发布、账号额度及旧历史兼容的可靠衔接。

## Impact

- 后端新增 `app/knowledge/`、增量 Alembic 迁移、知识库任务执行入口与配置；共享模块仅作有测试保护的可选字段、鉴权清理和发布适配。
- 新接口集中在 `/api/v1/knowledge/`；旧 `/materials/*`、`/quiz/*`、答题和报告接口保留现有契约。
- 前端新增知识库管理、问答与知识库出题流程，接入现有“私有知识库”入口，复用来源阅读、主题多选及关卡展示。
- 新增 `chromadb`、`langchain-chroma`、`langchain-text-splitters`；Embedding 使用独立百炼适配器，继续使用现有 DeepSeek 和 Tavily。依赖需与当前 Python 3.13、LangChain 1.x 和锁文件实测兼容。
- 本次只生成规划文档，未批准实施；不安装依赖、不迁移数据库、不修改业务代码，也不自动调用收费模型。
