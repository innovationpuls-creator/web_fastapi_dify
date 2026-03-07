# 前端说明

## 基本信息

前端是一个独立的 React + TypeScript 应用，负责提供会话式聊天界面、消息流式渲染、图片上传交互、历史会话入口和桌面/移动双端体验。

当前技术栈：

- React 18
- TypeScript
- Vite
- Framer Motion
- Tailwind CSS
- Vitest + Testing Library
- Playwright

应用入口位于 [`frontend/src/main.tsx`](src/main.tsx)，页面根组件位于 [`frontend/src/App.tsx`](src/App.tsx)。

## 页面与状态结构

### 页面骨架

`App.tsx` 负责把页面拼成三块：

- `SidebarHistory`
  - 桌面端历史会话侧栏。
- `ChatViewport`
  - 消息列表与屏幕级状态展示。
- `ComposerPanel`
  - 输入框、上传预览、发送/停止按钮。

移动端 history 则由 `MobileHistorySheet` 单独承接。

### 状态控制层

前端没有把全部状态塞进单个组件，而是分成 3 个 controller hook：

- `useConversationController`
  - 管理会话列表、详情缓存、当前会话、历史侧栏状态和导航切换。
- `useComposerController`
  - 管理输入框、上传队列、拖拽/粘贴、错误提示和上传生命周期。
- `useChatStreamController`
  - 管理流式发送、停止、乐观消息、reconcile 和异常恢复。

### feature helpers

`src/features/chat` 下的模块负责把复杂逻辑从 UI 中抽离：

- `model.ts`
  - 放共享类型和通用辅助函数。
- `conversationState.ts`
  - 处理会话列表和详情的纯状态变换。
- `streamSession.ts`
  - 负责构建一次发送会话的运行时快照。
- `streamLifecycle.ts`
  - 负责 assistant 消息增量更新、替换、收敛等纯逻辑。
- `uploadHelpers.ts`
  - 负责上传前校验和上传队列数据构造。

### 服务层

- `services/api.ts`
  - 封装前端与后端的 JSON 请求、上传请求和 NDJSON 流读取逻辑。

## 这次修改与新增模块的理念

### 1. 输入、会话、流式状态分层管理

聊天应用最容易失控的地方是状态交织。这次整理的核心思路是：

- 输入归输入。
- 会话归会话。
- 流式运行时归流式运行时。

这样可以避免 `App.tsx` 变成一个无法维护的超级组件。

### 2. 乐观渲染优先，再做 reconcile

- 用户发送后，前端会先插入 user message 和 assistant 占位消息。
- 当后端返回 `meta / delta / done / error` 后，再对这条消息进行增量修正。
- 这样既保证了响应速度，也给异常恢复留出了明确落点。

### 3. 桌面与移动入口分离，但语义保持一致

- 桌面端使用左侧栏。
- 移动端使用 sheet/dialog。
- 两者虽然表现形式不同，但都围绕同一套会话状态与操作语义组织，避免逻辑分叉。

### 4. 可访问性、错误恢复和测试不是附属功能

- 发送、停止、重试、上传错误、历史抽屉关闭这些都被纳入交互设计。
- 针对核心流程补了单测和 smoke test，降低 UI 回归风险。
- 这类工作会让前端更像产品，而不是一次性的演示页。

## 环境变量

前端主要依赖两个环境变量：

- `VITE_API_BASE_URL`
  - 后端 API 基础地址，默认 `http://127.0.0.1:8000`
- `VITE_ASSET_BASE_URL`
  - 可选，图片资产单独域名时使用

示例见 [`frontend/.env.example`](.env.example)。

## 启动与测试

### 安装依赖

```powershell
cd frontend
npm install
```

### 启动开发环境

```powershell
cd frontend
npm run dev
```

### 运行检查

```powershell
cd frontend
npm run lint
npm run test
npm run build
npm run test:e2e
```

## 建议阅读顺序

如果你要继续开发前端，推荐按下面顺序读代码：

1. `src/App.tsx`
2. `src/services/api.ts`
3. `src/hooks/useConversationController.ts`
4. `src/hooks/useComposerController.ts`
5. `src/hooks/useChatStreamController.ts`
6. `src/features/chat/*`
