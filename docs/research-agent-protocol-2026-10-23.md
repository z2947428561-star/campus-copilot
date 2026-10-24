# XMUMDorm Web 接入：协议与身份核查

日期：2026-10-23。范围：两仓库源码只读核查与官方文档研究；没有启动服务、读取环境变量文件或实现接入。结论是保留 Python Agent 服务，在 Dorm Express 增加受保护的代理入口，Web 先接入，App 后续复用接口和事件解析。

## 已实现的能力与实际缺口

| 项目 | 源码确认的现状 | 接入影响 |
|---|---|---|
| Campus 身份 | Bearer 是随机不透明 token，按哈希查表得到用户名；不是 JWT。[认证实现](<E:/Campus Copilot/src/auth.py:172>) | Dorm JWT 直接转发会认证失败。 |
| Dorm 身份 | 验 JWT 后校验正整数用户 ID，再查询 MySQL 用户状态，最后设置 `req.user`。[身份中间件](<C:/Users/阴沛森/Desktop/XMUMDorm-2.0.0-LYZZ/middleware/auth.js:19>) | 新代理必须先经过现有中间件，不能只解码 token 或接受请求体中的用户 ID。 |
| Campus 流 | `POST /api/chat` 返回 `text/event-stream`；帧格式为 `data: {JSON}\n\n`，JSON 的 `type` 才是事件类型。[序列化](<E:/Campus Copilot/src/server.py:262>)、[响应](<E:/Campus Copilot/src/server.py:517>) | 沿用 Fetch POST；无需为流式聊天改 WebSocket。 |
| Dorm 请求工具 | `request()` 消费完整 JSON 或完整文本，没有转交 `signal`；`requestRaw()` 也会读 JSON。[request.js](<C:/Users/阴沛森/Desktop/XMUMDorm-2.0.0-LYZZ/shared/api/request.js:48>) | SSE 不能经过这两个现有方法。应新增流式方法，复用 token/base URL 约定。 |
| Web 与 App 配置 | `getToken()` 支持宿主注入；base URL 同样有注入入口。[token](<C:/Users/阴沛森/Desktop/XMUMDorm-2.0.0-LYZZ/shared/api/request.js:24>)、[platform](<C:/Users/阴沛森/Desktop/XMUMDorm-2.0.0-LYZZ/shared/api/platform.js:31>) | 将事件解析与平台 UI 分开；无需复制两份协议。 |
| 会话归属 | Campus 先查会话归属，再由服务端构造内部 `thread_id`。[入口](<E:/Campus Copilot/src/server.py:392>)、[ID 构造](<E:/Campus Copilot/src/conversations.py:89>) | 对外只接收 `conversation_id`，不要开放任意 `thread_id`。 |
| 断线行为 | 队列容量 128；空闲约 0.5 秒发注释心跳；断线停止交付，后台执行继续并落历史。[EventStream](<E:/Campus Copilot/src/agent/web_runs.py:62>)、[落库与释放](<E:/Campus Copilot/src/server.py:492>) | “取消接收”不能宣传为“停止模型计算”；断线后查状态，不自动重发 POST。 |
| 并发与持久化 | 会话运行锁在单个 Python 进程内；checkpointer 支持 SQLite/Postgres。[运行锁](<E:/Campus Copilot/src/agent/web_runs.py:15>)、[存储工厂](<E:/Campus Copilot/src/agent/memory.py:66>) | 第一版继续单 worker；换 Postgres 不会自动得到跨进程互斥。 |

## 最小身份桥接方案（设计建议，尚未实现）

`Web/App → Dorm /api/agent/* → 现有 authenticateToken → 服务端签发短期内部断言 → Campus 内部认证适配 → 原有会话/Agent 逻辑`。

建议内部断言使用独立密钥和明确的 `iss`、`aud`、`sub`、`iat`、`exp`；固定允许的签名算法，强制这些字段及短有效期。`sub` 用经过 Dorm 验证的稳定数字 ID，Campus 映射为类似 `dorm:123` 的命名空间，避免与原本用户名碰撞。不复用 Dorm 登录 JWT 的密钥，不把内部断言发给浏览器，不接受浏览器自报的身份头。内部入口只允许可信网络访问，跨主机走 TLS。这是结合本项目身份差异作出的设计选择；JWT 的算法、发行者、主体、受众验证及不同用途令牌隔离，依据 [RFC 8725 §3](https://www.rfc-editor.org/rfc/rfc8725.html#section-3)。

对外初期只代理聊天、会话列表、新建会话、会话详情；增加所需接口时逐项放行。Campus 原来的登录、数据库浏览、成绩修改等接口不应因通配代理一起暴露。每次请求经过 Dorm 用户状态检查；后续个人业务工具仍需执行自己的资源权限校验。

## Web 流读取与错误约定（设计建议）

新增 `shared/api/agent.js` 的 `streamChat(body, onEvent, { signal })`，使用现有 token/base URL 规则及 Fetch POST。复用 Campus 已有解析逻辑：流式 UTF-8 解码、跨块缓存、空行分帧、CRLF、多行 `data:`、忽略注释心跳。[现有解析器](<E:/Campus Copilot/frontend/js/api.js:40>)。Fetch 标准支持请求 method/headers/body/signal，以及可逐块读取的 `Response.body`；原生 `EventSource` 的构造参数只含 URL 和凭据选项，不能直接表达本协议的 POST JSON 与自定义 Bearer 头。[Fetch 标准](https://fetch.spec.whatwg.org/#body-mixin)、[EventSource 标准](https://html.spec.whatwg.org/multipage/server-sent-events.html#the-eventsource-interface)。

事件处理必须覆盖：

- `token`：追加 `text`。
- `interrupt`：收集全部动作，保存 `checkpoint_id`、动作顺序与允许的决定；此分支正常断流且不发 `done`。
- `limit`：提示额度或步数限制；递归超限分支也可能直接结束流。
- `done`：本轮正常结束，更新额度信息。
- `error`：展示错误；网络 EOF 本身不等于成功，异常断流后读取会话详情核对 `running`、历史及待确认动作。

上述分支来自 [Campus 事件生产](<E:/Campus Copilot/src/server.py:449>)。不要将它们误写成 SSE `event: token` 监听器。收到 interrupt 后，以同一 `conversation_id`、最新 `checkpoint_id` 和完整 `decisions` 再 POST；Campus 已拒绝陈旧确认和数量不匹配的决定。[确认校验](<E:/Campus Copilot/src/server.py:311>)。

流开始前，先检查 HTTP 状态和 Content-Type，并保留 Dorm 的错误体：其 401 表示缺少 token，403 还可能包含账号状态或处罚语义，不能一概清空登录。Campus 的 `{detail}` 错误应由代理转换为 Dorm 的 `{status:-1,message}`，同时保留 409/422/429 等 HTTP 状态；内部断言被拒绝是服务连接故障，应报告网关错误，不能让用户重新登录来修复。流开始后无法改 HTTP 状态，采用 SSE `error` 或关闭流并让客户端查会话。已有请求工具的错误语义见 [request.js:91](<C:/Users/阴沛森/Desktop/XMUMDorm-2.0.0-LYZZ/shared/api/request.js:91>)。

App 当前声明 Expo `~57.0.26`。[package.json](<C:/Users/阴沛森/Desktop/XMUMDorm-2.0.0-LYZZ/app/package.json:32>)。Expo 57 官方提供 `expo/fetch` 流式示例；App 阶段可由宿主注入兼容 transport，保留同一解析器，不在 shared 中加入平台判断。真实设备上的中英文跨块解码、后台切换和 abort 仍需实测。[Expo 57 文档](https://docs.expo.dev/versions/v57.0.0/sdk/expo/#expofetch-api)。

## Express 代理与部署注意点（设计建议）

代理应在上游鉴权/校验通过之后再发送 SSE 响应头，逐块转发原始字节；不要 `await upstream.text()` 或用 `res.json()` 包装流。`Content-Type: text/event-stream`、`Cache-Control: no-cache`、`X-Accel-Buffering: no` 应保留，及时 flush headers。

Node 写入返回 false 时必须等待 `drain`，同时处理连接关闭/错误，不能一直排队读上游。可以使用具备背压的流管道，或显式处理 `res.write()`；选择一种实现即可。[Node Stream](https://nodejs.org/api/stream.html#event-drain)。

用 `res.close` 配合是否已正常完成的标记取消上游 Fetch，并清理监听器和读取器。不能简单把 `req.close` 当作浏览器取消：Node 自 v16 起，入站请求的 close 可以表示请求体接收完成；`ServerResponse.close` 则涵盖响应完成或响应提前断开。[Node HTTP](https://nodejs.org/api/http.html#event-close_2)。这只释放代理与 Campus 间的交付连接；Campus 后台 worker 继续运行的语义保持不变。

若实际部署经过 NGINX，应对聊天路径关闭响应缓冲，并设置适合模型等待时间的读取超时；例如 `proxy_buffering off; proxy_read_timeout 120s;`，数值是起始建议，需要实测。NGINX 默认启用响应缓冲，`X-Accel-Buffering: no` 可以控制它，但可能被配置忽略；`proxy_read_timeout` 是两次读取之间的空闲超时，默认 60 秒，不是总回答时长。[NGINX buffering](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_buffering)、[NGINX timeout](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_read_timeout)。

本次没有确认线上入口实际使用 NGINX，也未验证 Railway/其他托管入口的最长连接时间。没有必要仅为接入新增 NGINX。已确认 Web 开发代理把 `/api` 转发到 4040，因此 `/api/agent/*` 可以沿用现有路径。[Vite 配置](<C:/Users/阴沛森/Desktop/XMUMDorm-2.0.0-LYZZ/frontend/vite.config.js:50>)。部署 Node 版本未在根 package.json 声明；实现前确认实际运行时对 Fetch、AbortController 及选用流 API 的支持。

## LangGraph 语义与首轮验收

Checkpointer 保存单一 thread 的图状态；store 保存跨 thread 的应用数据；它们都不等于文档向量知识库。恢复 interrupt 必须使用原 thread ID；中断节点恢复时从节点开头重新执行，因此未来接入创建待办、报名等写操作时，确认之前的副作用应避免或保证幂等。[持久化](https://docs.langchain.com/oss/python/langgraph/persistence)、[中断恢复](https://docs.langchain.com/oss/python/langgraph/interrupts)。当前 Campus 已有持久 checkpointer、服务端 thread 构造和 checkpoint 版本校验，应直接复用。

实施后只需先验证关键闭环：两个账号不能互读会话；停用账号不能新发请求；中文/emoji 被拆块仍可逐字显示；代理不会等到整段完成才显示；断网后不重复执行且可刷新恢复历史；同会话并发返回 409；过期确认返回 409；interrupt 的 approve/reject 可继续同会话；模型不可用时保留 Dorm 其他功能。以上是待执行的验收建议，本次未运行这些测试。
