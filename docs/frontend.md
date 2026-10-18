# 前端模块与阅读顺序

前端代码独立放在 `frontend/`，后端仍位于 `src/`。这是代码与职责的分离，不是拆成两个服务：本机 FastAPI 同时提供首页、`/assets/` 静态资源和 `/api/` 接口，浏览器使用同源相对路径请求，无需配置 CORS、Node.js 构建工具或另一个前端端口。

## 文件结构

```text
frontend/
├── index.html
├── database.html
├── css/
│   ├── app.css
│   └── database.css
└── js/
    ├── app.js
    ├── api.js
    ├── session.js
    ├── auth.js
    ├── chat.js
    ├── student-data.js
    └── database.js
```

## 一个一个怎么读

| 顺序 | 文件 | 内容 |
| --- | --- | --- |
| 1 | [index.html](../frontend/index.html) | 页面结构：登录区域、聊天区、确认条、个人数据面板；通过模块脚本加载 `app.js`，没有内联事件处理器 |
| 2 | [app.css](../frontend/css/app.css) | 页面布局、颜色、组件状态和响应式断点；本次只抽取原样式，没有重新设计页面 |
| 3 | [app.js](../frontend/js/app.js) | 启动入口：创建功能模块、绑定按钮和键盘事件、协调登录与退出；401 时统一清理界面和会话 |
| 4 | [session.js](../frontend/js/session.js) | 读写 localStorage 中的 token 和用户名，保留原有 `cc_token` / `cc_user` 键；不包含密码 |
| 5 | [api.js](../frontend/js/api.js) | JSON 请求、Bearer token、HTTP 错误、401 通知与 SSE 解析；处理跨块 UTF-8、CRLF 和最后一帧 |
| 6 | [auth.js](../frontend/js/auth.js) | 登录/注册校验、按钮忙碌状态、登录区域显示与退出请求；真正的身份校验仍在 Python 后端 |
| 7 | [chat.js](../frontend/js/chat.js) | 会话选择与新建、历史和待确认恢复、流式更新及限额反馈；重置时丢弃旧请求结果 |
| 8 | [student-data.js](../frontend/js/student-data.js) | 个人数据面板、课程/成绩列表和增删操作；重置时取消请求并清空个人数据界面 |
| 9 | [database.js](../frontend/js/database.js) | 独立数据浏览器入口；共用 API 与会话模块，提供表格、字段、关联及详情，账号变化时取消请求并清理数据 |

功能模块通过小接口交给 `app.js` 协调，不相互导入。HTTP 和 SSE 只在 `api.js` 实现，存储键只在 `session.js` 管理；新增功能不应复制请求或 token 处理。动态消息和数据用文本节点渲染，不能把模型回复或课程字段当 HTML 插入。

`src/server.py` 使用 `StaticFiles` 将 `frontend/` 映射为 `/assets/`，首页返回 `frontend/index.html`。首页和静态资源设置 `Cache-Control: no-store`，本机修改后刷新即可。已有账号库、后端 API 和默认 `8000` 启动方式不变；不要直接双击 HTML，也不要把项目根目录整体当静态目录公开。

## 浏览器回归

前提：已安装项目 Python 依赖，并且命令行可用 `playwright-cli`。它只用于测试，不是运行网页的必要依赖。所有命令从项目根目录执行。

第一个终端启动专用测试应用：

```bash
python scripts/run_frontend_test_app.py
```

脚本固定监听 `127.0.0.1:18765`，跳过 `.env`，使用临时 SQLite 保存账号和个人数据，并从公开种子创建临时校园库，关闭追踪；Agent 使用本地确定性假模型、虚构 GPA 工具与临时 SQLite 检查点。不会修改日常账号库、公共课程库或读取原始经验表；正常退出后清理临时数据库。

第二个终端运行浏览器检查：

```bash
playwright-cli -s=frontend-migration open http://127.0.0.1:18765/
playwright-cli -s=frontend-migration run-code --filename=scripts/test_frontend.js
playwright-cli -s=frontend-migration close
```

结束后在第一个终端按 Ctrl+C。重复完整测试前重启测试应用，得到空的临时账号库；测试使用随机虚构账号，不要对日常 `8000` 应用运行。浏览器测试产物保存在被 Git 忽略的 `.playwright-cli/`。

测试使用真实注册、登录和个人数据 API；聊天通过真实 HTTP、Agent 图和本地假模型生成，不调用外部模型。覆盖注册规则、登录/刷新/退出、课程与成绩增删、中文 SSE 分块、会话新建/切换/刷新、历史与多动作确认恢复、并发与断连恢复、额度耗尽后的新建会话、登录过期处理和手机宽度布局，并检查页面 JavaScript 异常。这能验证浏览器交互与协议，不能证明真实模型回答质量、真实业务工具效果或 PostgreSQL / Milvus 集成正确。

`python scripts/check_offline.py` 另行检查首页与静态资源可访问、资源缓存策略及静态目录边界。GitHub Actions 运行此离线检查，目前不自动运行浏览器测试。

## 会话交互

顶部会话选择器在手机和桌面都可用。当前选择按用户名保存在 sessionStorage，各标签页可以独立选择。
刷新时从后端恢复检查点保留的消息和待确认动作；后台仍运行时自动刷新状态。
会话额度耗尽后保留记录并显示新建入口。详细协议与限制见[会话生命周期](conversations.md)。

## 数据浏览器

聊天页右上角“数据浏览器”打开 `/database`，功能和验证见[数据库可视化说明](database-browser.md)。
与聊天页面共用 token 和请求模块，独立 JavaScript 入口不创建 Agent。
追加浏览器检查命令为 `playwright-cli -s=campus-database run-code --filename=scripts/test_database_browser.js`。
