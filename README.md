# LevelUProject

微信小程序 + Python/FastAPI + MySQL。微信登录 → 学习主题、文档、公开网页或视频字幕 → 确认学习范围 → DeepSeek 出题与独立依据审核 → 服务端判分与奖励 → 云端历史、错题重温、知识地图、周期复盘报告与分享。

原始需求、方案与 `prototype/` 保留。前端使用当前原型的布局、原始吉祥物及图标；首页生成、空态引导及其他主操作按钮统一使用蓝色，黄色用于标题划线等装饰。

答题支持任意切题与上一题／下一题，全部作答后结算，首次答案锁定。新生成关卡每题首次答对：入门 10 XP＋2 金币，进阶 15 XP＋3 金币；历史奖励不追溯，重闯与复习不重复发奖。头像可预览、保存到相册及更换，页面返回保留滚动位置。

所有闯关来源支持手动开启“生成图片”（默认关闭），使用百炼 qwen-image-2.0 生成 512×512 配图并转存腾讯云 COS。默认每人每天最多 20 次请求，额度不足或生图失败仍返回文字题目；历史、报告、重闯及错题复习复用原图。配置、运行与验收见 [题目配图说明](docs/quiz-images/README.md)。

## 本地启动（Windows PowerShell）

需要 Python 3.11+、Node.js 20+、npm、MySQL 8.0+。当前验收使用 Python 3.13.9、Node.js 24.14.1、MySQL 8.0.45。前端统一维护在 `frontend/`，已移除不再使用的 `frontend-comic/` 目录。

```powershell
# 首次安装
./scripts/setup.ps1
# 参照 backend/.env.example 配置 MySQL、微信和身份摘要密钥，保留原有 AI 配置

# 一键启动：后端 + 微信小程序持续编译
.\start.bat

# 或启动后端 + H5 浏览器预览
.\start.bat -Target h5

# 后端 + 知识库任务 + 微信编译 + H5 预览一起启动
.\start.bat -Target all

# 只检查环境，不启动服务
.\start.bat -Check
```

也可直接双击根目录的 `start.bat`，默认启动微信开发环境；脚本从自身位置定位项目，不要求先切换终端目录。MySQL 需已运行。脚本检查依赖与端口、执行数据库迁移，再启动后端、已配置的知识库执行器与前端；微信模式在开发者工具导入 `frontend/`。保持启动窗口打开，按 Ctrl+C 停止本次启动的进程。同一项目重复启动时直接提示已有启动器，不重复启动编译或迁移；切换微信、H5 或同时启动模式前先停止原启动窗口。已运行且包含本轮接口的后端会复用，退出时保留该已有服务；被无关或旧服务占用的端口会提示处理，不自动终止其他进程。

启动日志集中在 `backend/logs/` 和 `frontend/logs/`。追加 `-Check` 可仅检查依赖及端口。仍可分别运行 `scripts/start-backend.ps1` 和 `scripts/start-h5.ps1`；只想持续编译微信前端时，在 `frontend/` 执行 `npm run dev:weapp`。

若旧终端提示找不到 `node.exe`，一键启动脚本会先查当前 PATH，再读取 Windows 已保存的系统／用户 PATH，并检查 `NODE_HOME`、`NVM_SYMLINK` 和常见安装目录。启动时会显示实际使用的 Node.js 路径及版本，要求 20+；无需为此修改系统环境变量。自定义安装位置或需要切换版本时，可通过 `-NodePath` 指定 `node.exe`，例如：

```powershell
# 先检查环境；将路径替换为本机实际安装位置
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start.ps1 -NodePath "D:\development\nodejs\node.exe" -Check
# 检查通过后启动 H5；微信小程序模式省略 -Target h5
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start.ps1 -NodePath "D:\development\nodejs\node.exe" -Target h5
```

若尚未安装 Node.js，先安装包含 npm 的 Node.js 20+，重新打开终端后再运行 `scripts/setup.ps1`。`-Check` 不连接数据库、不执行迁移，也不启动服务；它不能确认 MySQL 账号密码是否正确。

若迁移日志提示 MySQL `1045 / Access denied`，核对 `backend/.env` 中的 `MYSQL_HOST`、`MYSQL_PORT`、`MYSQL_USER` 和 `MYSQL_PASSWORD` 是否属于当前运行的 MySQL 实例。修正配置后重新执行启动命令。

若提示 `1049 / Unknown database`，但数据库工具中可以看到该库，先核对工具与后端连接的地址、端口和 MySQL 实例，不要直接重建数据库。本机曾同时安装 `MySQL` 和 `MySQL80`，分别使用 D 盘安装目录下的 `data/` 与 `C:/ProgramData/MySQL/MySQL Server 8.0/Data/`；原业务库在前者。当前已保留 `MySQL` 自动启动，将 `MySQL80` 停止并改为手动启动，避免两项服务争用 3306。切换服务会中断该实例的现有连接，启动脚本不会自行切换。

H5：http://127.0.0.1:10086 ；API 文档：http://127.0.0.1:8000/docs 。H5 仅用于本地预览和测试，正式登录需在微信小程序中完成。已构建预览也可以通过 `python scripts/serve_h5.py` 启动。

本地后端启动脚本会自动加载 `backend/app/` 下的 Python 代码更新。若自行启动了旧服务，新增接口返回 404 时先检查 `http://127.0.0.1:8000/docs` 的接口清单，再重启旧服务；微信前端重新编译不会更新后端进程。数据库迁移或 `.env` 配置变化仍需重新运行启动脚本。自动加载仅供本地开发，生产部署不使用 `--reload`；参数依据 [Uvicorn 官方设置](https://github.com/kludex/uvicorn/blob/main/docs/settings.md#development)。

MySQL 需事先创建业务库 `levelup` 和专用测试库 `levelup_test`，采用 utf8mb4，并授予配置账号对应库的迁移与读写权限。启动脚本自动执行 Alembic 迁移；不删除业务数据。已有部署升级前请备份业务库。正常运行必须保持 `DATABASE_TESTING=false`；测试流程显式启用独立测试库，名称必须以 `_test` 结尾且与业务库不同。测试会重置专用测试库，不能与其他测试同时运行。

`backend/.env` 已被 Git 忽略。AppSecret、数据库密码、AI 密钥与 `IDENTITY_HASH_SECRET` 仅保存在后端；身份摘要密钥至少 32 字符，部署后保持稳定。自动安装只在 `.env` 不存在时复制样例。

若本机执行策略阻止脚本，可直接执行脚本中的命令，不必修改系统执行策略。已配置的本地密钥不会包含在构建产物中。

## 构建微信小程序

```powershell
cd frontend
npm run build:weapp
npm run check:startup
```

微信开发者工具导入 `frontend/`，配置读取 `project.config.json`，产物在 `frontend/dist/`。前后端 AppID 必须一致。更新代码后使用“普通编译”；如果出现 `n[e] is not a function` 等模块加载错误，先重新构建，再在工具中清除编译缓存后普通编译。此前用户系统已人工确认启动、真实登录及头像昵称；本轮新增联网出题的开发者工具和真机验收状态见 [本轮验收记录](docs/quiz-grounding/验收记录.md)。

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

真实联网出题评测入口：在 `backend/` 执行 `.venv/Scripts/python.exe scripts/live_grounding_eval.py` 先检查配置，按 [评测说明](docs/quiz-grounding/真实评测.md) 确认范围后加 `--run` 调用 Tavily / DeepSeek。仅使用专用测试库，会产生服务调用费用；不清空业务库、不把降级当作联网成功。微信授权仍需在开发者工具单独验证。此前用户系统证据见 [用户系统验收记录](docs/user-system/验收记录.md)；首版历史资料见 [原验收报告](docs/implementation/验收报告.md)。

## 多源输入与个人分析

首页文档入口支持文字版 PDF、DOCX、TXT。PDF 可指定页码，DOCX 按段落与表格顺序读取；扫描 PDF、加密 PDF 和旧版 DOC 会提示替代操作。默认每份最多 20 MB、200 页 PDF、10 万字符。解析完成后先确认知识点，再出题；题目讲解可回看来源、页码或字幕时间。

网页由后端校验公开 HTTP/HTTPS 地址，再通过官方 LangChain TavilyExtract 读取指定页面的实际返回正文；链接和学习说明会发送至服务方，上传文档由本机解析。默认不扩展外链，允许联网补充时才由 Agent 自主调用 Tavily Search / Extract。B站和 YouTube 入口只读取可访问的中英文字幕，支持时间范围；字幕需登录、地区或网络受限时提示粘贴笔记。历史网页供应商的验收不能代替本轮 Tavily 实测，真实服务状态见本轮验收记录。

复盘中心的知识地图、数据分析和周期报告读取本人云端完整学习历史。分析按题数加权，仅统计已完成的新学关卡；复习影响知识点掌握估计，重闯不重复计入。周期报告支持近 7 天、近 30 天和最长 366 天的自定义时段，保留可信统计快照、前期比较、薄弱点建议及 TXT 导出。报告成功后复用，失败可重试，退出后可从已生成报告列表查看。

升级时重新安装 `backend/requirements.lock` 并执行原有启动脚本，增量迁移到 `006_retrieval_audit`。新增范围准备、调用计数和来源审计字段，不重写旧题库 JSON；升级前备份业务库。以下配置只写在后端 `.env`：

| 配置 | 默认值 / 作用 |
| --- | --- |
| `TAVILY_API_KEY` | 官方 Tavily Search / Extract 的后端密钥；用于网页读取和联网补充 |
| `JINA_API_KEY` | 仅保留旧配置兼容，网页读取和联网补充已不使用 |
| `SOURCE_TIMEOUT_SECONDS` | 30 秒 |
| `MATERIAL_MAX_BYTES` / `MATERIAL_MAX_PAGES` / `MATERIAL_MAX_CHARS` | 20971520 / 200 / 100000 |
| `MATERIAL_DAILY_LIMIT` / `PERIOD_DAILY_LIMIT` | 每账号每天 20 次解析 / 5 次实际周期报告调用 |

所有模型调用继续共用账号并发和分钟限流。未被关卡引用的材料 24 小时后清理；已引用材料随学习记录保留，注销时删除。微信文件上传和 TXT 文件分享还需在开发者工具及真机验收。

本轮 TDD、完整测试结果、原型截图、真实 DeepSeek/Jina 联调及未通过项目见 [多源输入与个人分析验收记录](docs/multisource/验收记录.md)。可在 `backend/` 执行 `.venv/Scripts/python.exe scripts/live_materials_eval.py --sources-only` 单独检查来源；不带该参数会另行调用真实模型并产生费用，只创建、删除自身临时账号。

## 联网依据出题

首页关键词先由同时具备官方 Tavily Search / Extract 的 Agent 获取资料，再确认领域、方向和知识点。复杂知识可取正文，简单知识可取摘要；条数、时间、语言和地域由 Agent 在白名单内选择。全球知识不限定国家，国家只作相关性偏向，城市通过地名与消歧核对。

网址和附加学习说明进入指定网页材料，保留“允许联网补充”开关。出题与独立依据审核在后台进行，等待分钟额度时展示真实阶段；返回首页或断网后可按原操作恢复。资料不足会标注“未联网核实”，纯网址不可读时要求正文或明确主题。

`QUIZ_GROUNDING_ENABLED=false` 可暂停新主题准备/后台出题，已有学习和原操作结果继续可用。准备每天默认20次；阶段预算、来源快照、旧材料同步兼容和恢复步骤见 [发布说明](docs/quiz-grounding/发布说明.md)。[验收记录](docs/quiz-grounding/验收记录.md) 区分受控回归、实际服务和微信人工结果。2026-10-14已完成20例真实联网出题、60题，结构与引用ID完整性检查通过。用户确认微信实际流程均成功及题目核对结果正确，已按对话总体确认登记，[逐题核对页](docs/quiz-grounding/live-runs/review-20261014.html)保留题目、引用和确认依据；未收到逐项表单、设备版本或截图，不补造这些材料。

## 数据与规则

- 默认 5 题/入门，可选 3 题/进阶。5 题为 3 单选 + 1 多选 + 1 判断，3 题各 1 道。
- 选择答案先保留草稿，可任意切题；最后一题统一提交，服务端已确认的答案锁定，提交中断后重试剩余答案。
- 首次新学答对按难度发奖：入门 +10 XP、+2 金币，进阶 +15 XP、+3 金币；每累计 100 XP 升一级，重闯、复习、恢复不重复发奖。
- MySQL 保存账号资料、关卡、答案、进度、报告、错题和奖励流水。本机只保存按账号隔离的缓存与登录凭证；旧游客记录保留本机，不自动导入账号或兑换奖励。分析只统计已完成的新学记录，按题数计算正确率。
- 导出 CSV 包含真实逐题答案与讲解。清理草稿不删历史；清空待复习队列仅将现有错题移入已掌握，历史答案保留。
- 后端逐题判分、锁定首答并发奖；报告仅接受本人已完成的轮次 ID。未提交题目的正确答案与解析不会提前下发。
- 每人每日 10 次新关卡、每滚动 60 秒 10 次实际 AI 调用（包括内部重试）、同时仅 1 个生成操作；所有阈值可配置。模型已开始调用的失败操作也占用额度。每份报告最多首次加 2 次手动重试，成功结果直接复用。
- 退出撤销当前 7 天会话。注销须二次确认及当前微信重新验证，删除个人资料与学习数据；当期防刷摘要和计数保留至周期结束后自动清理，防止当天注销重注册刷新额度。
- 知识库完整管理、提醒、好友 PK、会员、订单、装扮与成就仍保留原型入口并提示后续开放。

## 目录

- `backend/app/`：配置、微信登录、用户与学习服务、额度、模型适配、评分与 API；`backend/migrations/`：版本化建表。
- `backend/tests/`：TDD 自动化测试；`backend/test-results/`：RED/GREEN、覆盖率、真实 AI 结果。
- `frontend/src/`：Taro/React 页面与组件、登录态、账号缓存、平台与 Canvas 能力。
- `frontend/dist/`、`frontend/dist-h5/`：微信与 H5 构建产物。
- `frontend/logs/`：本地构建和测试原始日志，按开发基线和功能分类归档；保存方法见 [日志说明](frontend/logs/README.md)。
- `artifacts/levelup-weapp.zip`、`artifacts/levelup-h5.zip`：可复制的构建压缩包。
- `docs/user-system/`：本次用户系统验收、截图与测试报告；`docs/用户系统扩展方案.md`：已人工批准的方案。
- `docs/multisource/`：多源输入与个人分析验收、TDD 证据及原型对照截图；`docs/多源输入与个人分析开发方案.md`：已批准的开发步骤与口径。

技术文档来源记录在 [开发记录](docs/implementation/开发记录.md)。
