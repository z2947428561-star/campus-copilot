# Dorm 个人课表与待办

校园助手现可只读查询当前登录账号最近导入的网站课表和待办，并读取网站共享的“放假日”数据。可以直接问：

- 我今天有什么课？
- 查我下周一的课程、时间和教室。
- 我有哪些未完成的待办？
- 明天到期的待办有哪些？
- 查看已完成的待办，或下一页待办。
- 下次放假是什么时候，还有几天？
- 这学期有什么节日？
- 2027 年圣诞节是哪天？

不新增、修改、删除或完成待办，不创建提醒。查询成功后直接回答所问记录；未导入课表与没有课程分开说明。日期范围不在日历覆盖范围、服务失败时不推断为没课。

## 本地启动

在 Campus 目录执行 `run_dorm_web.cmd --existing-database --local-kb`，再打开 `http://127.0.0.1:5173/agent`。入口位于左侧“万能墙”上方，旧路径 `/myzone/agent` 自动跳转。该模式使用 Dorm 已有的数据库配置和真实登录，不运行迁移或后台任务。

启动器每次生成临时内部共享密钥，并同时传给 Dorm 和 Agent，不写入配置文件。手动启动时，两边需配置相同且至少 32 字符的 `CAMPUS_AGENT_SHARED_SECRET`；Dorm 设置 `CAMPUS_AGENT_URL` 为 Agent 地址，Agent 设置 `XMUMDORM_API_URL` 为 Dorm 的服务端地址，例如 `http://127.0.0.1:4040`。HTTP 只允许回环地址，远程地址需 HTTPS。禁止将共享密钥加上 `VITE_` 前缀或交给浏览器。

## 查询含义

- 使用 `Asia/Kuala_Lumpur` 时区和网站共用学期日历计算今天、明天、本周、下周。课程记录尚无独立学期版本，只能反映最近导入的网站课表。
- 待办默认查询所有日期下的未完成事项，包含无截止日期事项；今天、明天、指定日期按截止日期筛选，不包含无日期事项。
- 逾期与网站现有页面一致：截止日期早于今天。当天已经过了截止时间的事项仍归在今天。
- 待办每页 20 条，可继续查询下一页；单次课程查询最多 200 条，截断会标记，不能声称列完。

## 身份与接口

Web 登录经过原有 Dorm 校验后，以短期内部断言进入 Agent。查询工具从受验证的运行上下文取账号，不提供用户编号、令牌或 URL 参数给模型。

Agent 回查 `GET /internal/campus-agent/personal/clock`、`/schedule`、`/todos`、`/holidays`。回查断言使用独立 issuer/audience、60 秒有效期；原 Web 登录令牌或进入 Agent 的断言不能替代它。接口重新检查账号状态、按账号限流并禁止缓存；个人业务 SQL 只执行绑定当前账号的 SELECT，假期从共享配置读取。其他方法和未知参数不受支持，数据库错误不返回给模型。

## 放假日

工具 `get_campus_holidays` 直接复用 Dorm `shared/config/holidays.js`，和 Web/App 的放假日页面同源。维护者更新该共享配置后，重启 Dorm 服务即可使用新记录，无需导入知识库或生成向量。

支持下一次、之后已收录、本学期、今年、指定年份、今天、明天、指定日期和日期范围，也可按节日中英文名称筛选。倒计时、假期持续天数按学校时区计算；学期查询按共享学期起止日期筛选，保留跨年元旦和同日、重叠假期。

这些是模块已收录的公共假期，数据并非完整校历；未收录时不推断“没有假期”或“当天必须上课”，不据此判断寒暑假、考试、调课或个人课程取消。回答继续遵守问什么答什么，不附来源式开头。

`scripts/verify_dorm_holidays.py` 用真实模型、虚构账号与固定测试日历验证最近放假、倒计时、本学期、指定节日、未收录年份和日期。报告保存至 `data/local/xmumdorm/holiday-verification/check.json`。测试时钟只影响日历，短期断言始终使用认证时钟。

2026-10-24 本地验收：Node 代理及业务查询 21 项、Python 个人工具及 Dorm 集成 9 项通过；真实模型 5 类问答通过，未收录情况另加 2 条简短回答验证通过。真实账号网页提问“下次放假是什么时候，还有几天？”实际调用假期工具成功，日期和倒计时与右侧放假日一致。截图为 `data/local/xmumdorm/agent-holidays.jpg`，网页调用报告为 `data/local/xmumdorm/holiday-verification/web-check.json`。未修改共享假期记录或生产业务数据，仅本地接入。

个人记录正文只是数据，不作为指令执行。个人记录会作为模型生成答案的上下文；本轮真实模型自动验收使用隔离的虚构记录，没有向模型传入生产个人记录。

## 验证

在 Campus 运行 `scripts/test_dorm_personal.py` 验证内部签名、固定回查地址、输入范围及真实 Agent 图的身份注入。`scripts/check_offline.py` 包含该检查。

在 Dorm 运行 `npx jest __tests__/routes/agentPersonal.test.js __tests__/routes/agent.test.js --runInBand`，验证跨账号隔离、只读接口、参数绑定、日期周次和分页。

在 Campus 运行 `scripts/verify_dorm_personal.py` 验证真实模型通过实际 Node 路由查询隔离虚构记录。它使用本地端口 18768，不加载 Dorm 数据库配置，不写入生产数据；结果保存至 `data/local/xmumdorm/personal-verification/check.json`。

### 2026-10-24 本地验收

- Python 个人查询 6 项、Dorm 代理和个人接口 17 项通过；包含伪造 runtime 仍只能查询受验证账号的回归。
- 真实模型 4 类隔离样例通过：下周一课表、未完成待办、另一账号空待办、未导入课表。历史与最终回答一致。
- 已登录的真实 Web 提问“查一下我今天的课表和未完成的待办。”，两项工具实际回查成功，回答为今天无已录课程、无未完成事项；重新打开页面后恢复一致。仅查询，没有写入生产业务记录。
- 完整离线回归 22 个检查文件通过。首轮既有 Chroma 恢复测试遇到一次索引磁盘读取错误，未改该模块，完整复跑通过；日志保存在 `data/local/xmumdorm/personal-verification/offline-check.log`。
- Web 调用状态报告为 `data/local/xmumdorm/personal-verification/web-check.json`，截图为同目录 `web-proof.jpg`。改动仅在本地，未提交、推送或部署。
