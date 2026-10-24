# 题目配图：配置与运行

本次方案于 2026-10-22 获用户“按方案开发”确认。主题、文档、网页、视频和知识库关卡均可选择配图；开关默认关闭。重闯、错题复习和历史回看复用原图。

## 配置

按照 backend/.env.example 配置，密钥只写在后端本机 .env，不写入前端、测试结果或聊天。安装更新的 requirements.lock，执行原有启动脚本，增量迁移到 010_image_dispatch（包含配图表、画面描述计划和跨进程发送节奏）。

已有环境在项目根目录执行依赖更新，随后使用现有启动脚本（启动时自动迁移）；不需要重建原数据库：

```powershell
python -m pip --python backend/.venv/Scripts/python.exe install -r backend/requirements.lock
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/start.ps1 -Target h5
```

单独迁移时，在 backend 目录执行 `.venv/Scripts/python.exe -m app.migrate`。正式运行知识库出题仍按项目原有方式启动知识库 Worker，API 与 Worker 读取相同后端环境变量。

启动脚本复用现有后端之前会检查配图能力接口；缺少新接口的旧服务不会被误当作升级后的后端。若提示 8000 被旧服务占用，停止原服务后重新启动。

- IMAGE_API_KEY、IMAGE_BASE_URL 为空时复用已配置的 KNOWLEDGE_EMBEDDING_API_KEY、KNOWLEDGE_EMBEDDING_BASE_URL；不要求启用知识库。使用北京百炼业务空间的原生 /api/v1 地址，不使用 DeepSeek 或 OpenAI 兼容模式地址。
- 模型 qwen-image-2.0，分辨率 512*512，每题 n=1。默认最多五题在途并发；IMAGE_MIN_REQUEST_INTERVAL_SECONDS 默认 0.55 秒，API/Worker 通过 MySQL 共享预订发送时间。连接准备完成后等待预订时间，过期名额重新排队，适配每秒 2 次的上游限流。无自动付费重试。
- COS_SECRET_ID、COS_SECRET_KEY、COS_REGION、COS_BUCKET 在服务端读取；COS_BUCKET 包含 APPID 后缀。
- COS_PUBLIC_BASE_URL 使用可长期访问图片的 HTTPS 地址，不含签名查询参数。推荐自定义域名/CDN；需为专用 question-images/ 路径配置公开读取，或配置具有源站访问权限的公开 CDN。不要把存放私有原始文档的目录公开。
- COS 默认域名可能受预览策略限制，应实测内嵌图片；本次配置的默认域名在 Chrome 内嵌读取 512×512 图片通过。正式微信环境还需配置对应 HTTPS 合法域名并实机验证。

## 额度、超时与保留

每个微信身份每天默认 20 次生图请求，按 Asia/Shanghai 自然日计算。实际开始的调用即计数，生图失败、下载失败、上传失败或响应丢失均不返还；尚未开始的题目不计数。剩余两张额度的五题关卡只尝试两张，其余返回文字并给出友好说明。

调用前使用独立 MySQL 日计数和唯一逐题调用记录，不在云端请求期间持有数据库锁。同一操作恢复只复用已有成功 URL，不重新发出已开始、失败或结果不明的请求。进程恰好在请求发出前后退出时采用保守记账，避免不确定状态下重复付费。

图片只有在题目通过原有独立依据审核后才生成。先由现有文字模型批量转换为纯画面描述，正常每轮增加一次文字调用，计入原有文字模型调用和速率预算；不向生图模型发送题干、选项、答案或解析。描述计划持久保存，恢复时不重新调用；描述失败只发布文字。IMAGE_STAGE_TIMEOUT_SECONDS 默认 90 秒，包含描述和等待发送的时间；单次生图默认 60 秒，下载/上传各 15 秒。图片阶段还受任务剩余时间限制并为文字题目发布留出余量。等待发送时取消或超时的预留请求释放额度；已发出请求不自动退额或重试。失败时正常保存文字，不修改题量、答案、判分、奖励或来源核实状态。

已保存图片随题目快照复用；账号注销保留当日防刷计数到当天结束。所有预留对象键会登记清理任务，最长云端工作排空后再删除（默认至少等待 10 分钟，避免刚删除又被迟到上传重新创建），失败自动重试。关闭新配图不会取消已有清理；清理仍需要有效的 COS 凭据。

## 测试与真实联调

2026-10-24：真实五题全部生成、转存 COS 并在浏览器展示，答题、历史、重闯和跨登录复用通过，额度仅扣 5 次。已解决文字海报、新 OSS 域名和请求限流问题。全量 710 项回归基线及最终 80 项配图复测通过，合并核对 712 个不同后端用例；前端 65 项及类型检查通过，详见 [本轮联调记录](live-20261024/联调记录.md)。微信真机仍待验收。下述开发验收记录为 2026-10-22 的历史结果。

2026-10-22 自动验收：后端 689 项、前端 65 项、浏览器 5 项通过；当时配图模块综合覆盖率 97.9%。H5/微信构建、微信官方样式编译与启动检查通过。详见 [验收记录](验收记录.md)。

自动化只使用经过隔离校验的 MySQL 测试库和临时知识库索引；生图、下载和 COS 边界由受控替身模拟。RED/GREEN 和回归结果保存在 test-results/。不得并行运行两个会重置该测试库的后端测试进程。

开发阶段用户选择先完成自动测试；现已配置并完成真实百炼、COS 及浏览器验收。微信实际环境仍不能由替身测试或构建成功代替。

后端回归在 backend 目录执行 `.venv/Scripts/python.exe -m pytest`；前端在 frontend 目录执行 `npm test`、`npm run typecheck`、`npm run build:h5` 和 `npm run build:weapp`。浏览器专用服务为 `tests.serve_question_images_e2e`（18001 端口，仅测试库和云端替身），静态 H5 测试页使用 18086 端口；对应 `npx playwright test --config=playwright.images.config.ts`。后端数据库测试和浏览器服务不得同时运行。

## 接口兼容

主题/材料 `POST /api/v1/quiz/generate` 及知识库 `POST /api/v1/knowledge/quizzes` 均接受可选布尔 `generate_images`，缺省或 false 不生图。主题/材料默认关闭时沿用旧幂等摘要；开启后该参数参与任务身份，恢复原任务必须使用原请求体。

鉴权后的 `GET /api/v1/quiz/images/capabilities` 返回 `available`、`reason_code`、`remaining`、`daily_limit` 和 `resolution`；不会调用云端。原有“每日关卡额度”与配图额度分别展示、分别计数。

每题新增可空 `image_url`。开启配图的关卡额外保存 `image_generation: {requested, generated, reason_code}`；例如只剩两张额度的五题关卡为 `{requested:5, generated:2, reason_code:"IMAGE_DAILY_LIMIT"}`。前端据此提示部分未配图，HTTP 出题流程仍成功。图片阶段为 `generating_images`，原有题目审核、答案隐藏、判分和奖励逻辑继续适用。旧快照缺失这些字段仍可读取。

## 关闭和回退

设置 `QUIZ_IMAGES_ENABLED=false` 后重启 API 和 Worker，即可关闭新生图；文字出题与已存配图仍可使用。保留 008–010 表和 COS 对象，避免破坏历史快照或注销清理。清理既有对象仍需要有效 COS 配置。

本次增量迁移新增五张表，不重写原题库。仅空的受保护表允许回退；存在调用、用量、描述计划、发送状态或对象记录时拒绝删除，跨版本回退会在删除任何新表前检查旧版本受保护数据，避免 MySQL 非事务 DDL 留下半完成状态。正常回退采用关闭功能开关，不需要回退数据库。

## 技术依据

通过 Context7 核对 DashScope 同步多模态端点、Tencent COS Python SDK 的 CosConfig/CosS3Client/put_object 和 Taro Image/Switch 用法，并核对本机安装 SDK 的构造签名与重试逻辑。

- https://www.alibabacloud.com/help/zh/model-studio/qwen-image-api （生图临时链接有效期 24 小时，及时转存）
- https://github.com/tencentyun/cos-python-sdk-v5 （本次锁定 1.9.44，Python 3.13 安装及 import 通过）
- https://cloud.tencent.cn/document/product/436/56882 （公有图片 URL 及自定义域名说明）
- https://docs.taro.zone/docs/components/media/image （图片缩放和错误回调）
