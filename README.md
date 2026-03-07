# ChatFlow Core AI

## 项目定位

ChatFlow Core AI 是一个以前后端解耦方式实现的多轮对话系统：后端提供基于 FastAPI 的会话、流式输出、图片上传与健康检查能力，前端提供桌面/移动兼容的聊天界面、历史会话管理和流式交互体验。

这个仓库最初以 `dify-fastapi` 为后端代号演进而来，目前已经整理成一个可直接运行、可测试、可发布的完整项目骨架，并以 `v1.0.0` 作为首个正式版本节点。

## 核心能力

- 基于会话持久化的多轮聊天，不再依赖一次性上下文拼接。
- 支持图片上传、图片资产落盘和后续轮次复用。
- 支持 NDJSON 流式输出、取消生成、失败恢复与状态回写。
- 提供独立前端，覆盖桌面侧栏历史、移动端 history sheet、发送/停止/重试等核心交互。
- 具备后端单测、前端单测、前端构建和 Playwright smoke test 基础验证链路。

## 目录结构

```text
.
|- backend/      FastAPI 后端、业务服务、持久化、测试
|- frontend/     React 前端、状态控制、页面组件、测试
|- data/         本地运行时数据库与图片资产目录（默认不入库）
|- main.py       仓库根入口，导出 FastAPI app
|- README.md     项目总览
```

## 前后端职责边界

### 后端负责

- 会话、消息、上传、资产的持久化与读写顺序稳定性。
- 与 OpenAI-compatible `chat.completions` 接口通信。
- 流式消息生命周期管理，包括 `meta / delta / done / error` 事件。
- 取消生成、健康检查、请求日志和统一错误返回。

### 前端负责

- 用户输入、上传、会话切换、历史面板和流式渲染体验。
- 针对流式聊天的乐观更新、失败恢复、停止生成和状态同步。
- 多端 UI 适配、基础可访问性和前端回归测试。

## 本项目修改与新增模块的总体理念

这次改造不是简单“加接口”或“补页面”，而是把项目往一个可以持续演进的会话式 AI 应用整理：

- 以会话为中心：消息、会话摘要、图片资产都围绕长期会话组织，便于继续扩展搜索、归档、分享等能力。
- 以状态可恢复为前提：无论是后端流式生成还是前端乐观渲染，都优先保证“可中断、可回写、可恢复”。
- 以前后端解耦为基础：后端专注业务与持久化，前端专注交互与状态编排，降低后续替换模型或重做界面的成本。
- 以模块化替代堆叠式逻辑：后端拆分 router/service/repository，前端拆分 controller hooks、feature helpers 与 UI components，减少单点复杂度。
- 以质量门禁支撑发布：把测试、构建和可访问性当作功能的一部分，而不是上线前临时补救。

## 快速开始

### 1. 准备环境变量

仓库根目录：

```powershell
Copy-Item .env.example .env
```

前端目录：

```powershell
Copy-Item frontend/.env.example frontend/.env
```

### 2. 启动后端

```powershell
uv --directory backend sync
uv --directory backend run uvicorn main:app --reload --app-dir .. --env-file ..\.env
```

### 3. 启动前端

```powershell
cd frontend
npm install
npm run dev
```

默认情况下：

- 后端服务地址：`http://127.0.0.1:8000`
- 前端开发地址：`http://127.0.0.1:5173`

## 测试方式总览

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

## 文档导航

- 后端说明：[`backend/README.md`](backend/README.md)
- 前端说明：[`frontend/README.md`](frontend/README.md)

如果你准备继续开发，建议阅读顺序是：

1. 先看本文件了解整体边界。
2. 再看 `backend/README.md` 理解数据流和 API 组织。
3. 最后看 `frontend/README.md` 理解状态编排和页面结构。
