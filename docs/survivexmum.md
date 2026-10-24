# SurviveXMUM 公开文章采集

运行 `scripts/crawl_survivexmum.py` 下载学生维护的公开 Wiki Markdown。采集结果暂存本机，
不会自动写入现有政策知识库、调用模型或重建向量索引。

2026-10-03 检查时，`https://surivivexmum.wiki/api/wiki/manifest` 列出了 73 个条目。
正文由 `/api/wiki/page?path=...` 提供，字段为 `content`，另有 `version`、`lastUpdated`。
接口与前端数据来源也见[站点项目文档](https://github.com/503133214/SurviveXMUM#内容从哪里来)。
首页、robots.txt 和 sitemap.xml 的初次检查均返回 SPA HTML；没有找到有效的 robots 规则或 sitemap。
这不代表站点授权任意用途。脚本仅请求上述匿名公开阅读接口，每次至少间隔 2 秒。

## 配置

在项目根目录创建 `.env.survivexmum`，填入 Webshare 的一个代理：

```dotenv
WEBSHARE_PROXY_HOST=代理IP
WEBSHARE_PROXY_PORT=代理端口
WEBSHARE_PROXY_USERNAME=代理用户名
WEBSHARE_PROXY_PASSWORD=代理密码
```

脚本只读取此文件，不读取应用 `.env` 或进程中的代理变量。不使用 Webshare API key。
密码含 `#` 或空格时请用单引号包裹整个值；URL 特殊字符会由脚本自动编码。
`.env.survivexmum` 和输出目录 `data/local/` 都已被 `.gitignore` 忽略，不要公开提交或粘贴凭据。

## 运行

Windows 本机环境，在项目根目录执行：

```powershell
# 只测试目录：仍然必须走代理。
.\.venv\python.exe scripts\crawl_survivexmum.py --check

# 先抓两篇检查结果。
.\.venv\python.exe scripts\crawl_survivexmum.py --limit 2

# 抓取目录中的全部公开非草稿条目（包括网站开发文档）。
.\.venv\python.exe scripts\crawl_survivexmum.py

# 只抓生活与学习内容。
.\.venv\python.exe scripts\crawl_survivexmum.py --category 生活篇 --category 学习篇
```

标准 venv 的解释器路径是 `.venv\Scripts\python.exe`，Linux/macOS 使用 `python`。
依赖为 `requests` 与 `python-dotenv`，已列入项目 requirements.txt。
不设置 `track=1`，避免增加站点阅读计数。不会抓取图片、评论、登录、投稿或用户资料接口。

## 输出与失败处理

每次运行生成独立的 `data/local/survivexmum/<UTC时间>/` 快照目录：

- `manifest.json`：该次获取的导航与文章目录。
- `pages.jsonl`：每篇的 Markdown、原文 URL、分类、版本、站点更新时间、UTC 抓取时间和正文 SHA-256。
- `<路径哈希>.md`：原始正文；远端路径不会被当成本机文件路径。
- `snapshot.json`：`complete` 表示选定文章已全部保存；`incomplete` 表示失败或取消，仅供检查部分结果。

不会覆盖已有快照。重新运行会创建新的快照；当前仍逐篇下载，SHA-256 用于后续核对变化，
尚未实现跳过下载或更新向量库。入库时将 `source_type=student_wiki` 与来源元数据一起保留，
学生经验与官方政策应明确区分。

## 网络边界

脚本强制为 HTTP/HTTPS 配置同一个认证代理，在发送层检查代理配置。缺少凭据、代理连接失败、
403/429、重定向、无效响应都会停止，不重试、不切换出口、不回退直连。
`trust_env=False` 禁用环境代理/NO_PROXY 与 netrc；HTTPS 校验保持开启；
不发送 `Forwarded`、`X-Forwarded-For` 等来源 IP 头。
仅允许访问指定域名的两个 HTTPS 阅读接口，拒绝 HTTP、其他域名和其他接口。

代理地址须为 IP 字面量；目标域名通过 HTTP CONNECT 隧道交给代理，不由脚本在本机解析。
这个约束只覆盖此采集脚本，不会修改 Chrome、应用、Embedding、Git 或操作系统的联网方式。
脚本不加载正文中的外链图片。用其他软件预览 Markdown 或点击原文链接时，该软件的联网方式
不受此脚本保护；检查下载结果可以直接查看 `pages.jsonl` 文本。
目标网站通常看到代理出口 IP；Webshare 和本机网络仍能看到你与代理之间的连接，代理也可能添加自己的转发头。
这不是完全匿名保证。此前检查发生过直连，过去的网络记录无法由本脚本撤回。

离线验证只使用模拟响应和本机回环代理，不访问网站或公共 IP 检测服务：

```powershell
.\.venv\python.exe -m unittest discover -s scripts -p test_survivexmum_crawler.py
```

## 将已有正文导入助手

采集与入库是独立操作。新增 `scripts/import_local_wiki_guides.py` 可从已完整下载的本地快照导入社区指南库，不发出 Wiki 请求，也不需要代理配置：

```powershell
.\.venv\python.exe scripts\import_local_wiki_guides.py --snapshot-dir data\local\survivexmum\20261003T030225654751Z
```

导入前验证下载清单覆盖、正文 SHA-256 和原文 URL，只选择入学、生活、学习分类中的实质正文，剔除空白、标题/图片占位和贡献提示。保留 `student_wiki` 类型及真实出处元数据，不混入官方政策库。索引会调用现有 Embedding 服务。

当前已导入 24 篇、89 个片段，AC 系统、生活软件、学校网站账号三组真实检索通过。详细操作与完整快照替换规则见 [指南知识的导入与更新](dorm-guide-knowledge.md)。
