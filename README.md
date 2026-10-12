# LevelUProject

微信小程序 + Python/FastAPI + MySQL。微信登录 → 文本输入 → DeepSeek 出题 → 服务端判分与奖励 → AI 报告 → 云端历史、错题重温、分析与 PNG 分享。

原始需求、方案与 `prototype/` 保留。前端使用当前原型的布局、原始吉祥物及图标；首页生成、空态引导及其他主操作按钮统一使用蓝色，黄色用于标题划线等装饰。

答题支持任意切题与上一题／下一题，全部作答后结算，首次答案锁定。新生成关卡每题首次答对：入门 10 XP＋2 金币，进阶 15 XP＋3 金币；历史奖励不追溯，重闯与复习不重复发奖。头像可预览、保存到相册及更换，页面返回保留滚动位置。

## 本地启动（Windows PowerShell）

需要 Python 3.11+、Node.js 20+、npm、MySQL 8.0+。当前验收使用 Python 3.13.9、Node.js 24.14.1、MySQL 8.0.45。只维护 `frontend/`，另一套 `frontend-comic/` 不属于本次扩展。

```powershell
# 首次安装
./scripts/setup.ps1
# 参照 backend/.env.example 配置 MySQL、微信和身份摘要密钥，保留原有 AI 配置

# 终端一
./scripts/start-backend.ps1
# 终端二
./scripts/start-h5.ps1
```

H5：http://127.0.0.1:10086 ；API 文档：http://127.0.0.1:8000/docs 。H5 仅用于本地预览和测试，正式登录需在微信小程序中完成。已构建预览也可以通过 `python scripts/serve_h5.py` 启动。

MySQL 需事先创建业务库 `levelup` 和专用测试库 `levelup_test`，采用 utf8mb4，并授予配置账号对应库的迁移与读写权限。启动脚本自动执行 Alembic 迁移；不删除业务数据。已有部署升级前请备份业务库。正常运行必须保持 `DATABASE_TESTING=false`；测试流程显式启用独立测试库，名称必须以 `_test` 结尾且与业务库不同。测试会重置专用测试库，不能与其他测试同时运行。

`backend/.env` 已被 Git 忽略。AppSecret、数据库密码、AI 密钥与 `IDENTITY_HASH_SECRET` 仅保存在后端；身份摘要密钥至少 32 字符，部署后保持稳定。自动安装只在 `.env` 不存在时复制样例。

若本机执行策略阻止脚本，可直接执行脚本中的命令，不必修改系统执行策略。已配置的本地密钥不会包含在构建产物中。

## 构建微信小程序

```powershell
cd frontend
npm run build:weapp
npm run check:startup
```

微信开发者工具导入 `frontend/`，配置读取 `project.config.json`，产物在 `frontend/dist/`。前后端 AppID 必须一致。更新代码后使用“普通编译”；如果出现 `n[e] is not a function` 等模块加载错误，先重新构建，再在工具中清除编译缓存后普通编译。本次该操作后已由人工确认可以正常启动、真实微信登录及保存/恢复头像昵称。

首次登录使用默认头像和“好奇心同学”。在“我的”点击头像主动选择头像，点击昵称主动填写并保存；资料可跳过。微信身份登录不会自动读取昵称头像。登录页必须勾选协议；未登录无法进入学习页面或调用业务接口。

真机联调：后端以 `--host 0.0.0.0` 启动，构建时将 `API_BASE` 设置为电脑的局域网地址。开发工具本地验收可关闭合法域名检查；正式微信运行需要 HTTPS 后端，以及 request/uploadFile/downloadFile 合法域名配置。

```powershell
$env:API_BASE='http://你的电脑局域网IP:8000'
$env:MINI_CODE_URL='https://你的域名/真实小程序码.png'
npm run build:weapp
```

`MINI_CODE_URL` 为空时，海报显示“小程序码待配置”；不能将占位内容当作可扫码图片。好友卡片携带短主题，接收方从首页独立生成关卡。

## 验证

```powershell
./scripts/check.ps1
# 后端完整测试使用 levelup_test；正式后端可继续使用 levelup
cd backend
.venv/Scripts/python.exe -m tests.serve_accounts_e2e # 单独终端，测试服务 8001
cd ../frontend
npm run build:h5
npm run test:e2e # 需 H5 10086 和专用测试服务 8001
```

端到端测试使用本机 Chrome。微信和 AI 网络边界采用测试替身，业务逻辑、事务和数据使用真实 MySQL；测试服务仅监听本地 8001，正式 8000 服务没有绕过微信登录的入口。默认 Playwright 和 npm 命令均执行 `e2e-accounts/`；原 `e2e/` 为账号扩展前的历史用例。

可选真实 AI 联调：在 `backend/` 执行 `.venv/Scripts/python.exe scripts/live_accounts_eval.py`，会产生模型调用费用，只创建并删除自身测试账号，不清空业务库。微信授权仍需在开发者工具单独验证。最新范围、测试证据和运行边界见 [用户系统验收记录](docs/user-system/验收记录.md)；首版历史资料见 [原验收报告](docs/implementation/验收报告.md)。

## 数据与规则

- 默认 5 题/入门，可选 3 题/进阶。5 题为 3 单选 + 1 多选 + 1 判断，3 题各 1 道。
- 单选、判断选中即提交；多选显式提交。提交后锁定并立即保存。
- 首次新学答对 +10 XP、+2 金币，每累计 100 XP 升一级；重闯、复习、恢复不重复发奖。
- MySQL 保存账号资料、关卡、答案、进度、报告、错题和奖励流水。本机只保存按账号隔离的缓存与登录凭证；旧游客记录保留本机，不自动导入账号或兑换奖励。分析只统计已完成的新学记录，按题数计算正确率。
- 导出 CSV 包含真实逐题答案与讲解。清理草稿不删历史；清空待复习队列仅将现有错题移入已掌握，历史答案保留。
- 后端逐题判分、锁定首答并发奖；报告仅接受本人已完成的轮次 ID。未提交题目的正确答案与解析不会提前下发。
- 每人每日 10 次新关卡、每滚动 60 秒 3 次实际 AI 调用（包括内部重试）、同时仅 1 个生成操作；所有阈值可配置。模型已开始调用的失败操作也占用额度。每份报告最多首次加 2 次手动重试，成功结果直接复用。
- 退出撤销当前 7 天会话。注销须二次确认及当前微信重新验证，删除个人资料与学习数据；当期防刷摘要和计数保留至周期结束后自动清理，防止当天注销重注册刷新额度。
- 文档/网页/视频解析、知识库、地图、周期报告、提醒、好友 PK、会员、订单、装扮与成就均保留原型入口并提示后续开放。

## 目录

- `backend/app/`：配置、微信登录、用户与学习服务、额度、模型适配、评分与 API；`backend/migrations/`：版本化建表。
- `backend/tests/`：TDD 自动化测试；`backend/test-results/`：RED/GREEN、覆盖率、真实 AI 结果。
- `frontend/src/`：Taro/React 页面与组件、登录态、账号缓存、平台与 Canvas 能力。
- `frontend/dist/`、`frontend/dist-h5/`：微信与 H5 构建产物。
- `artifacts/levelup-weapp.zip`、`artifacts/levelup-h5.zip`：可复制的构建压缩包。
- `docs/user-system/`：本次用户系统验收、截图与测试报告；`docs/用户系统扩展方案.md`：已人工批准的方案。

技术文档来源记录在 [开发记录](docs/implementation/开发记录.md)。
