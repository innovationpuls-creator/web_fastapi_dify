# 后端说明

## 基本信息

后端基于 FastAPI 构建，负责承接会话式聊天的核心业务能力，包括健康检查、会话管理、图片上传、流式输出、取消生成以及本地持久化。

当前技术栈：

- FastAPI
- OpenAI-compatible `chat.completions`
- SQLite
- 本地文件系统图片资产
- `unittest` 作为基础测试框架

应用入口位于 [`backend/app/main.py`](app/main.py)，仓库根目录的 [`main.py`](../main.py) 负责导出同一个 `app`，方便本地启动与部署接入。

## 模块结构

### `chat`

- `router.py`
  - 暴露聊天、会话、上传、资产、取消等 HTTP 路由。
- `service.py`
  - 负责业务编排：准备输入、调用上游模型、生成流式事件、写回消息状态。
- `repository.py`
  - 负责 SQLite 持久化、消息顺序稳定性、会话摘要查询、上传和资产记录管理。
- `schemas.py`
  - 统一聊天相关请求与响应模型。
- `cancellation.py`
  - 管理正在流式生成中的取消状态和局部文本快照。

### `health`

- 提供轻量存活检查与深度上游连通性检查。
- 用于区分“应用活着”和“模型服务可用”这两个状态。

### `core`

- 集中管理配置、OpenAI 客户端创建、日志格式和统一 API 错误响应。

### `middleware`

- 提供请求级日志与 `request_id` 链路信息，便于排障和观测。

## 这次修改与新增模块的理念

### 1. API 以会话为中心

这次改造的核心不是“多加几个 endpoint”，而是把聊天接口从一次性上下文请求整理成会话式系统：

- 会话拥有标题、更新时间、最后消息预览和消息数量。
- 消息拥有明确的 `role / status / created_at / updated_at`。
- 前端不需要自己拼接历史上下文，后端直接从会话持久化记录中恢复对话链。

### 2. 流式输出必须可取消、可失败恢复、可持久化

- assistant 占位消息会在流开始前落库。
- 生成过程中的 `delta` 会持续累积，支持中途取消并保留已生成内容。
- 失败和取消都不是“消失”，而是明确写回 `failed` 或 `cancelled` 状态，方便前端恢复与排查。

### 3. 图片上传与正式资产分离

- 上传阶段先得到短期 `upload_id`，便于前端预览和重试。
- 真正发送消息时，再把上传内容转成会话级正式资产。
- 这样可以把“临时输入”与“会话资产”区分开，避免脏数据和无主文件堆积。

### 4. Repository 与 Service 分工明确

- Repository 只负责数据的可靠读写与排序稳定性。
- Service 负责业务状态迁移、上游调用、异常处理和流式事件产出。
- 这种分层让后续替换数据库、增加消息类型或扩展审计逻辑时更可控。

## 主要接口

- `GET /health`
  - 应用存活检查。
- `GET /health/deep`
  - 上游模型连通性检查。
- `GET /conversations`
  - 获取会话摘要列表。
- `GET /conversations/{conversation_id}`
  - 获取单个会话及其消息详情。
- `DELETE /conversations/{conversation_id}`
  - 删除会话和关联资产。
- `POST /conversations/{conversation_id}/messages/{message_id}/cancel`
  - 取消一条正在生成的 assistant 消息。
- `POST /chat/uploads`
  - 上传临时图片。
- `DELETE /chat/uploads/{upload_id}`
  - 删除未消费的临时上传。
- `GET /chat/assets/{asset_id}`
  - 读取已保存的会话图片资产。
- `POST /chat/stream`
  - 发起聊天并返回 NDJSON 流。

## 环境变量

最常用的配置项如下：

- `OPENAI_API_KEY`
  - 上游模型服务鉴权。
- `OPENAI_BASE_URL`
  - OpenAI-compatible 服务地址。
- `OPENAI_MODEL`
  - 默认使用的模型名。
- `OPENAI_SYSTEM_PROMPT`
  - 系统提示词。
- `CHAT_DATABASE_PATH`
  - SQLite 数据库路径。
- `CHAT_ASSETS_DIR`
  - 会话图片资产目录。
- `CHAT_UPLOADS_DIR`
  - 临时上传目录。
- `CHAT_MAX_IMAGES_PER_MESSAGE`
  - 单条消息允许的最大图片数。
- `CHAT_MAX_IMAGE_BYTES`
  - 单张图片最大字节数。

完整示例见仓库根目录 [`../.env.example`](../.env.example)。

## 启动与测试

### 安装依赖

```powershell
uv --directory backend sync
```

### 启动开发服务

```powershell
uv --directory backend run uvicorn main:app --reload --app-dir .. --env-file ..\.env
```

### 运行测试

```powershell
uv --directory backend run python -m unittest discover -s tests -v
```

如果你要继续演进后端，推荐优先阅读顺序：

1. `app/main.py`
2. `app/chat/router.py`
3. `app/chat/service.py`
4. `app/chat/repository.py`
