# 检索 Agent

使用现有 `ModelGateway.chat_model()`，通过 LangChain `create_agent` 同时注册 `tavily_search` 和 `tavily_extract` 类型化封装，原生异步执行。保留原模型配置和 `max_retries=0`。不添加自动切换模型、隐藏重试或其他工具。

Agent 自主选择次序、参数和停止时机。结果仅采用证据登记表，忽略 Agent 最终文字总结。无工具调用或不兼容的模型响应明确报错，不能冒充联网成功。

官方 ModelCallLimitMiddleware / ToolCallLimitMiddleware 设置运行上限，额外中间件在每次真实模型调用、每次工具尝试前执行账号计数钩子。工具批次串行预留并执行，避免并发越限；无效参数也占尝试次数但不发送外部请求。相同有效参数重复调用复用本操作结果，记录 cached，不再次付费。

保留结构化调用轨迹：工具名、参数、状态、真实用量（未知则空）、耗时和真实来源 ID；不记录正文、答案、密钥或原始供应商错误。模型使用量仅采集实际响应的非负 token 字段。累计上下文预算在实际模型调用前裁剪，历史工具资料重复传入同样计入。

只读指定网址时，程序同时检查禁止搜索及允许网址集合，正文无法改写权限。模型错误、账号钩子错误向上抛出；工具结果不足或检索预算用尽可交给后续范围整理处理。

已用真实 LangChain 图与可控模型、官方 SDK 模拟传输验证异步执行、自主次序、重复缓存、错误、权限与上限；生产账号持久预算接线按任务 4.5 完成。

官方依据：[自定义中间件](https://docs.langchain.com/oss/python/langchain/middleware/custom)、[内置限制中间件](https://docs.langchain.com/oss/python/langchain/middleware/built-in)，2026-10-14 通过 Context7 和锁定包源码核对。
