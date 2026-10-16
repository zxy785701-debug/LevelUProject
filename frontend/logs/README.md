# 前端日志

构建、测试和类型检查的临时日志统一放在本目录，不放在 `frontend/` 根目录。日志不提交 Git；正式验收证据保存在 `docs/`。

## 已归档日志

- `baseline/`：开发前的单元测试、类型检查基线及环境排查日志。
- `multisource/`：多源输入与个人分析开发过程中的测试、H5/微信构建、官方样式编译和启动检查原始日志。保留原文件名与内容；其中包含失败记录，文件名带 `green` 或 `final` 不代表最终验收通过。

最终结果以 [多源输入验收记录](../../docs/multisource/验收记录.md) 和 [用户系统验收记录](../../docs/user-system/验收记录.md) 中明确引用的记录为准。

一键启动时自动写入 `start-weapp.log` 或 `start-h5.log`，对应的错误输出为 `*.error.log`；每次启动覆盖该模式的本地日志。后端启动日志在 `backend/logs/start-backend.log` 和 `start-backend.error.log`，数据库迁移日志为 `start-migrate.log` 和 `start-migrate.error.log`。

## 保存新日志

在 `frontend/` 下执行，使用固定的 `latest` 文件名覆盖本地最新记录，避免反复生成散落文件：

```powershell
npm test *> logs/unit-latest.log
npm run typecheck *> logs/typecheck-latest.log
npm run build:h5 *> logs/h5-build-latest.log
npm run build:weapp *> logs/weapp-build-latest.log
npm run test:e2e *> logs/e2e-latest.log
```

默认命令仍直接输出到终端；需要保存时再重定向。需要长期保留的 RED/GREEN 或最终验收结果，整理到对应 `docs/*/test-results/` 并在验收记录中引用。
