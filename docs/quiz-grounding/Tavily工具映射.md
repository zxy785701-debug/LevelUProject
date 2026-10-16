# Tavily 双工具映射

实现固定使用官方 `langchain-tavily==0.2.18` 原生 `ainvoke`。每次调用创建独立工具实例，参数不会存入跨用户共享对象。以下映射已通过官方 SDK 到 HTTP 传输边界的请求检查；测试仅替换网络传输，不替换 SDK。

凭证在项目配置中保持 `SecretStr`，只在构造官方 Search / Extract 时调用 `get_secret_value()`。锁定SDK使用的 `get_from_dict_or_env` 会先将入参字符串化；直接传SecretStr会将脱敏星号误作实际凭证。已补两工具Authorization传输断言（全部虚构密钥）并验证真实搜索和指定网页读取成功，凭证不进入模型、日志或证据文件。

## Search

| AI 可选字段 | 官方工具位置 | 约束 |
| --- | --- | --- |
| query | invoke | 1–400 字符 |
| content_mode | constructor include_raw_content | summary → false；full → markdown |
| max_results | constructor | 1–10，且不能超过配置上限 |
| country | constructor | 官方枚举值，仅 general；无城市参数 |
| search_depth、topic、time_range | invoke | 白名单；全球搜索省略 country |
| start_date、end_date | invoke | ISO 日期；与 time_range 互斥 |
| include_domains、exclude_domains | invoke | 各最多 20 个纯域名，不重叠 |

固定禁止自动答案、图片及自动参数改写；请求真实 credits 用量，供应商没有提供则记为未知。未知字段、城市伪参数和不适用组合在请求前拒绝。API 地址及凭证不向 AI 开放。

工具的错误对象、空结果和外层超时返回安全错误码；不回传原始异常或把异常文字登记为证据。关闭官方 `handle_tool_error` 的文字转换以保留可辨别的异常路径。没有 Tavily 凭证不发送请求，不切换 Jina。

依据：[LangChain Search](https://docs.langchain.com/oss/python/integrations/tools/tavily_search)、[Tavily Search API](https://docs.tavily.com/documentation/api-reference/endpoint/search) 与锁定安装包源码，2026-10-14 核对。官方 API 上限可能更大，本项目使用设计批准的保守上限。

## Extract

每次最多 3 个公开 HTTP(S) 网址，固定 markdown、不取图片，沿用独立工具实例和外层超时。

- full：只传 urls、extract_depth；实际 HTTP 请求没有 query 或 chunks_per_source，取得供应商可访问的页面正文，不承诺网页全部动态内容均可读取。
- focused：同时要求 query 和 1–5 个 chunks_per_source；后者放在构造参数，前者放在 invoke。片段模式不能显示为整页读取。
- AI 可决定 basic 或 advanced 深度；重试/深度升级由上层 Agent 在预算内决定，工具封装不暗中重试。
- HTTP 200 同时检查 results 和 failed_results。空正文、缺失页面、错误对象、超时、供应商全部失败都不作为证据；部分失败保留成功内容及安全错误码。
- 官方 SDK 在全部失败时抛出 ToolException，无法取得原始逐页错误；这种情况按请求网址逐项记录未读取成功，不猜测失败原因。

依据：[LangChain Extract](https://docs.langchain.com/oss/python/integrations/tools/tavily_extract) 及锁定版本的实际 HTTP 参数。

## 材料入口迁移

网页读取使用 Extract full；网页正文中的链接仅作为文本，不自动跟随扩展。材料补充使用 Search，只有用户开启补充才调用；后续 Agent 任务将统一负责检索规划。两个入口和 `search_available` 均只检查 `TAVILY_API_KEY`，旧 `JINA_API_KEY` 保留配置兼容但不再用于网页和补充，也不在失败时自动切回 Jina。

文档上传的 PDF/DOCX/TXT 解析及公开视频字幕读取保持原路径。网页读取前取得账号操作租约；取消后不继续整理并释放租约。网页的学习说明随材料保存，整理范围时仍受材料内容限制。
