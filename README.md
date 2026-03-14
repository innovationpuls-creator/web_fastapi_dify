# ChatFlow Core AI

一个以前后端解耦方式实现的会话式 AI 聊天项目：后端提供 FastAPI + SQLite + OpenAI-compatible 流式接口，前端提供 reading-first 的聊天体验、历史会话管理、图片上传和多端交互。

## 产品亮点

- Reading-first 聊天界面：用户消息气泡更明确，AI 回复更像可阅读的正文内容。
- Sidebar 历史分组：按 `Today / Yesterday / Earlier` 分组展示会话。
- 更克制的历史操作：删除收进 `⋯` 菜单，支持 inline rename。
- 开发者可见指标：展示 `Tokens` 与 `Latency`。
- 最后一轮快捷操作：支持 `Edit` 用户消息与 `Regenerate` AI 回复。
- 支持图片上传、流式输出、取消生成和失败恢复。

## 当前版本说明

当前仓库保留的是稳定的 reading-first 版本：

- 保留阅读优先 UI、会话重命名/删除、时间分组 sidebar、Tokens/Latency、最后一轮 Edit/Regenerate。
- 不包含后续实验性的流式动画投影架构。
- 目标是先保证稳定、清晰、可维护，再继续做新的流式体验迭代。

## 技术栈

### 后端

- FastAPI
- OpenAI-compatible `chat.completions`
- SQLite
- 本地文件系统图片资产
- `unittest`

### 前端

- React 18
- TypeScript
- Vite
- Tailwind CSS
- Framer Motion
- React Markdown + `remark-gfm`
- Vitest + Testing Library
- Playwright

## 目录概览

```text
.
|- backend/       FastAPI 后端、聊天服务、持久化与测试
|- frontend/      React 前端、聊天 UI、状态控制与测试
|- data/          本地数据库与图片资产目录
|- main.py        仓库根入口，导出 FastAPI app
|- README.md      项目总览
```

## 核心能力

### Reading-first 聊天体验

- AI 消息按正文排版，Markdown 层级更清晰。
- 用户消息保留更明显的右侧气泡区分。
- 支持思考态、正文态、截断提示和图片消息。

### 会话管理

- 左侧会话列表支持时间分组。
- 历史项提供 `Rename / Delete` 菜单。
- 支持会话标题更新、会话详情读取与删除。

### 流式交互

- 使用 NDJSON 按事件流式返回聊天结果。
- 支持取消生成、失败回写和状态恢复。
- 最后一轮消息支持 `Edit` 与 `Regenerate`。

### 媒体与资产

- 支持临时上传图片。
- 发送消息时将上传内容转为正式会话资产。
- 会话删除时可清理关联资产。

## 快速开始

### 1. 准备环境变量

复制根目录环境变量：

```powershell
Copy-Item .env.example .env
```

复制前端环境变量：

```powershell
Copy-Item frontend/.env.example frontend/.env
```

常用后端变量：

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `OPENAI_MODEL`
- `CHAT_DATABASE_PATH`
- `CHAT_ASSETS_DIR`
- `CHAT_UPLOADS_DIR`

常用前端变量：

- `VITE_API_BASE_URL`
- `VITE_ASSET_BASE_URL`

### 2. 启动后端

```powershell
uv --directory backend sync
uv --directory backend run uvicorn main:app --reload --app-dir .. --env-file ..\.env
```

默认地址：`http://127.0.0.1:8000`

### 3. 启动前端

```powershell
cd frontend
npm install
npm run dev
```

默认地址：`http://127.0.0.1:5173`

## 测试命令

### 后端

```powershell
uv --directory backend run python -m unittest discover -s tests -v
```

### 前端

```powershell
cd frontend
npm run lint
npm run test
npm run build
npm run test:e2e
```

## 前后端职责

### 后端负责

- 会话、消息、上传和资产的持久化。
- 与上游 OpenAI-compatible 服务通信。
- 生成 NDJSON 流事件并处理取消、失败和状态回写。

### 前端负责

- 聊天页、sidebar、移动端 history sheet 和 composer 交互。
- 乐观更新、流式消息渲染、上传队列和错误提示。
- 会话切换、最后一轮操作和界面回归测试。

## 相关文档

- [backend/README.md](backend/README.md)
- [frontend/README.md](frontend/README.md)
