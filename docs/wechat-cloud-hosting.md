# 微信云托管 Docker 部署

2026-10-24 通过 Context7 查阅微信官方文档，结合当前 FastAPI 后端生成 `backend/Dockerfile`。本次仅增加容器构建文件和说明，不修改现有业务逻辑、不自动发布服务。

## 官方规范与本项目配置

| 项目 | 官方文档与本项目处理 |
| --- | --- |
| 自定义 Dockerfile | 控制台选择“有 Dockerfile 文件”，文件名与代码中一致。使用自定义文件时，Python 自动生成模式的依赖文件命名约定不适用；本项目保留 `requirements.lock`。 |
| 构建目录 | 选择仓库中的 `backend` 作为代码根目录／目标目录，Dockerfile 名称填 `Dockerfile`。镜像内的 `WORKDIR /app` 是运行目录，与平台构建目录不同。 |
| 网络监听 | 启动命令监听 `0.0.0.0:8080`；控制台服务端口也填 `8080`。80/8080 是示例或项目选择，不把某一个端口说成所有自定义镜像的强制值。一个服务只配置一个端口。 |
| 启动进程 | 一个 JSON 数组形式的 `CMD`，前台运行 Uvicorn，单进程，不启用开发用 `--reload`。没有依赖平台自动注入 `PORT`。 |
| 文件存储 | 容器写入的数据在重启、扩缩容后不保留；现有题目配图继续存放 COS，业务数据存放外部 MySQL。知识库限制见下文。 |
| 构建与运行隔离 | Python 3.13 Debian slim；编译工具仅存在于构建阶段；运行阶段使用普通用户，包含 HTTPS 根证书、时区数据和原生运行库。 |

依据：[微信版本管理](https://developers.weixin.qq.com/miniprogram/dev/wxcloudservice/wxcloudrun/src/guide/service/version)、[微信开发常识](https://developers.weixin.qq.com/miniprogram/dev/wxcloudservice/wxcloudrun/src/guide/debug/know)、[腾讯云官方部署排错](https://docs.cloudbase.net/run/faq/deploy)、[Docker 构建上下文](https://docs.docker.com/build/concepts/context/)、[Dockerfile CMD](https://docs.docker.com/reference/dockerfile/#cmd)。腾讯云部署排错还说明其云托管镜像需使用 AMD 架构；手动构建时下列命令显式指定 `linux/amd64`。

## 构建和运行

在项目根目录执行，命令最后的 `backend` 是构建上下文，不能换成 `.`：

```powershell
docker build --platform linux/amd64 -t levelup-api:latest backend
```

构建过程不需要 MySQL、AI 或 COS 密钥，不执行数据库迁移。`.dockerignore` 采用白名单；源码仅复制 `app`、`migrations` 和 `alembic.ini`，本机 `.env`、虚拟环境、知识库原始文件、日志、测试和前端都不进入镜像。

在云托管“环境变量”中参照 `backend/.env.example` 配置实际运行参数：

- `MYSQL_HOST`、`MYSQL_PORT`、`MYSQL_USER`、`MYSQL_PASSWORD`、`MYSQL_DATABASE`：使用云端可达的 MySQL。`127.0.0.1` 在容器内指容器自身，不能指向开发电脑的数据库。
- `WECHAT_APP_ID`、`WECHAT_APP_SECRET`、`IDENTITY_HASH_SECRET`：保留原有认证方式；若迁移已有用户，身份摘要密钥应与原环境相同。
- DeepSeek、Tavily、百炼与 COS：继续使用原有环境变量名。云托管不会自动把其数据库变量名转换成本项目的 `MYSQL_*`。
- `DATABASE_TESTING=false`；`KNOWLEDGE_ENABLED=false`，直到知识库完成后述适配。
- 如果 H5 也需要访问，`CORS_ORIGINS` 配置为 JSON 数组，填写实际 H5 域名。

不要把真实密钥写进 Dockerfile、构建参数或代码仓库。已有 `backend/.env` 是本地配置；本地测试容器时，可复制出一份不入库的云端配置，调整数据库地址后，通过 `docker run --env-file` 注入。

第一次部署和更新数据库结构时，在发布业务流量前，用同一镜像执行一次：

```powershell
# .env.cloud 仅作为本机运行参数文件，已被现有 .gitignore 排除。
docker run --rm --env-file .env.cloud levelup-api:latest python -m app.migrate

# 本地验证容器启动；云托管部署时用控制台环境变量代替 --env-file。
docker run --rm --env-file .env.cloud -p 127.0.0.1:8080:8080 levelup-api:latest
```

也可在能连接目标数据库的发布环境执行等价的一次性迁移。不要在 `docker build` 中迁移，也不要让每个自动扩容实例同时执行 Alembic。`app`、迁移目录与 `alembic.ini` 均已包含在镜像中。

访问 `/api/v1/health` 应返回 `code=0`。`/` 当前没有业务路由，返回 404 不等于启动失败。Dockerfile 的 `HEALTHCHECK` 检查应用存活；云托管自己的端口／健康检查仍须在控制台正确配置，不能依赖它自动读取 Docker `HEALTHCHECK`。存活检查不证明数据库配置、迁移或微信登录已经通过联调。

当前前端仍默认访问本机 `127.0.0.1:8000`。后端部署完成后，还需把前端构建参数 `API_BASE` 指向云端 HTTPS 地址，重新编译并配置微信合法域名。改为 `wx.cloud.callContainer` 需要额外适配前端，Dockerfile 不会自动完成此改动。

## 现有项目的云端适配边界

个人知识库将原始文件和 Chroma 索引写入本地私有目录，并依赖单独运行的 `python -m app.knowledge.worker`。API 容器单独启动不能提供完整知识库能力。不能通过把 Worker 再写成第二行 `CMD` 来启动，也不能把容器临时目录当作持久存储；需要先确定持久文件／向量存储和独立 Worker 的运行方案。

现有范围准备、材料处理和出题还使用响应后的后台任务，应用也有常驻清理循环。微信文档明确提醒不要依赖请求结束后继续执行的后台例程。将实例下限设为 1 可以避免缩容至 0 的冷启动，但不能替代后台任务适配或保证发布、实例重启时的任务完成。正式上线前，应将这些任务迁移到可恢复的独立执行器并完成真实部署验证；本次生成 Dockerfile 不意味着完整异步流程已经在云平台验收。

## 验证状态

已检查复制路径、JSON 启动命令、监听地址、端口与普通用户配置；应用内请求验证 `/api/v1/health` 返回 200／`code=0`，未登录访问 `/api/v1/me` 仍返回 401，未调用数据库或 AI 服务。本机未找到 Docker CLI，因此尚未完成 Linux 镜像实际构建与容器运行。首次云端构建应确认锁定依赖在 Linux/Python 3.13 下均能安装，再验证 MySQL 迁移、微信登录和出题流程。Docker 构建时的 `pip check` 会阻止依赖关系不一致的镜像继续生成。
