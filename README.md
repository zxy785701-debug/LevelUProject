# LevelUProject MVP

微信小程序 + Python 无数据库后端。文本输入 → DeepSeek 出题 → 三类题型即时讲解 → 结算 → AI 报告 → 本机历史、错题重温、分析与 PNG 分享。

原始需求、方案与 `prototype/` 保留。前端使用当前 v5 原型的颜色、布局、原始吉祥物及图标；首页生成按钮保留黄色，指定底部主行动保留蓝色。

## 本地启动（Windows PowerShell）

需要 Python 3.11+、Node.js 20+、npm。当前验收使用 Python 3.13.9、Node.js 24.14.1。

```powershell
# 首次安装
./scripts/setup.ps1
# 编辑 backend/.env，仅在后端填写 DEEPSEEK_API_KEY

# 终端一
./scripts/start-backend.ps1
# 终端二
./scripts/start-h5.ps1
```

H5：http://127.0.0.1:10086 ；API 文档：http://127.0.0.1:8000/docs 。已构建预览也可以通过 `python scripts/serve_h5.py` 启动。

若本机执行策略阻止脚本，可直接执行脚本中的命令，不必修改系统执行策略。已配置的本地密钥不会包含在构建产物中。

## 构建微信小程序

```powershell
cd frontend
npm run build:weapp
```

微信开发者工具导入 `frontend/`，配置读取 `project.config.json`，产物在 `frontend/dist/`。工程已配置开发用 AppID；其他开发者导入时请替换为自己的 AppID。真实登录、好友分享、真机相册授权和扫码需要相应的账号权限与平台配置。更新代码后使用“普通编译”；工程已关闭热重载，避免保留旧页面状态。

真机联调：后端以 `--host 0.0.0.0` 启动，构建时将 `API_BASE` 设置为电脑的局域网地址。开发工具本地验收可关闭合法域名检查；正式微信运行需要 HTTPS 后端与合法域名配置。

```powershell
$env:API_BASE='http://你的电脑局域网IP:8000'
$env:MINI_CODE_URL='https://你的域名/真实小程序码.png'
npm run build:weapp
```

`MINI_CODE_URL` 为空时，海报显示“小程序码待配置”；不能将占位内容当作可扫码图片。好友卡片携带短主题，接收方从首页独立生成关卡。

## 验证

```powershell
./scripts/check.ps1
cd backend
.venv/Scripts/python.exe scripts/live_eval.py # 使用本地真实密钥，产生模型调用费用
cd ../frontend
npm run build:h5
npm run test:e2e # 需 H5、后端运行；含一个真实模型联调用例
```

端到端测试使用本机 Chrome；未安装 Chrome 时可安装 Playwright Chromium 并移除配置中的 `channel: 'chrome'`。纯自动化出题/报告/异常分支测试使用可控模型替身；真实 AI 测试单独记录。测试结果、页面映射、微信补验步骤见 [验收报告](docs/implementation/验收报告.md)。

## 数据与规则

- 默认 5 题/入门，可选 3 题/进阶。5 题为 3 单选 + 1 多选 + 1 判断，3 题各 1 道。
- 单选、判断选中即提交；多选显式提交。提交后锁定并立即保存。
- 首次新学答对 +10 XP、+2 金币，每累计 100 XP 升一级；重闯、复习、恢复不重复发奖。
- 本机存储保存题库、答案、报告、未完成进度和错题掌握状态。分析只统计已完成的新学记录，按题数计算正确率。
- 导出 CSV 包含真实逐题答案与讲解。清理草稿不删历史；清空待复习队列仅将现有错题移入已掌握，历史答案保留。
- 后端重新计算报告统计，不接受客户端 `is_correct`、XP 或正确率。首版无账号、数据库与云备份；本机数据被清理后不可由后端恢复。
- 文档/网页/视频解析、知识库、地图、周期报告、提醒、好友 PK、会员、订单、装扮与成就均保留原型入口并提示后续开放。

## 目录

- `backend/app/`：配置、请求/模型输出校验、LangChain JSON 模式适配、评分与 API。
- `backend/tests/`：TDD 自动化测试；`backend/test-results/`：RED/GREEN、覆盖率、真实 AI 结果。
- `frontend/src/`：Taro/React 页面与组件、本机状态、平台与 Canvas 能力。
- `frontend/dist/`、`frontend/dist-h5/`：微信与 H5 构建产物。
- `artifacts/levelup-weapp.zip`、`artifacts/levelup-h5.zip`：可复制的构建压缩包。
- `docs/implementation/`：验收清单、截图与测试报告。

技术文档来源记录在 [开发记录](docs/implementation/开发记录.md)。
