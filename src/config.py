"""环境配置中心:所有可调参数集中在这里,业务代码不再读 os.environ。

课程对应:
    第02章 §1.2(p2)  参数写在配置文件里(推荐),不硬编码
    第02章 §3.3(p15-16)  temperature / max_tokens / timeout / max_retries
    第02章 §6.4(p62-65)  config / configurable_fields 的运行时覆盖
    第10章 §2.4.2(p48-49) Embedding 走 OpenAI 兼容云端网关(占位配置,key 后补)

设计理由:把"读环境变量"收敛到一处,好处是
1) 业务模块不依赖 os.environ 的键名,改名只改这里;
2) 缺 key 时能给出带指引的报错,而不是裸 KeyError(第02章 §5.5 p47 的失败处理)。
"""
import os

from dotenv import load_dotenv

# override 的取值规则(普通注释,不是代码):
#   override=True(默认)与课件示例一致 —— .env 优先于系统环境变量。
# 想用**只设环境变量**的方式临时切换配置(例如临时把 EMBED_BACKEND 换成本地
# Ollama 重建知识库,而不改 .env),就设 CAMPUS_ENV_OVERRIDE=0 ——
# 此时系统环境变量优先,.env 只填补未设置的项。
#
# 例外:测试脚本需要在 import 本模块**之前**用环境变量把库切到临时库/测试库,
# 若强制 override,.env 里的生产配置会把测试设置顶掉(实测踩到)。
# 因此支持 CAMPUS_SKIP_DOTENV=1 让测试完全接管配置。
if os.environ.get("CAMPUS_SKIP_DOTENV") != "1":
    load_dotenv(override=os.environ.get("CAMPUS_ENV_OVERRIDE", "1") == "1")


def _env(key: str, default: str = "") -> str:
    return (os.getenv(key) or default).strip()


def _env_float(key: str, default: float) -> float:
    raw = _env(key)
    try:
        return float(raw) if raw else default
    except ValueError:
        return default


def _env_int(key: str, default: int) -> int:
    raw = _env(key)
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


# ---------------------------------------------------------------- 主对话模型
# 课程 ch02 §3.1(p12-13) 推荐用 "provider:model" 冒号前缀或显式 model_provider。
# 注意:model_provider="deepseek" 需要额外安装 langchain-deepseek;
#      为了不引入新依赖,默认走课件 ch02 §2.2(p8) 的 OpenAI 兼容写法。
#      装了 langchain-deepseek 的话,把 LLM_PROVIDER 改成 deepseek 即可切换。
LLM_PROVIDER = _env("LLM_PROVIDER", "openai")          # openai | deepseek | ollama
LLM_MODEL = _env("LLM_MODEL", "deepseek-chat")
LLM_API_KEY = _env("DEEPSEEK_API_KEY")
LLM_BASE_URL = _env("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

# 课程 ch02 §3.3(p15-16):temperature 0.0-0.3 用于数学计算、数据提取、分类、代码生成。
# 本项目大量场景是"抽取事实 / 算 GPA / 路由工具",所以取低温而非默认的 0.7。
LLM_TEMPERATURE = _env_float("LLM_TEMPERATURE", 0.2)
LLM_MAX_TOKENS = _env_int("LLM_MAX_TOKENS", 2048)
LLM_TIMEOUT = _env_float("LLM_TIMEOUT", 60.0)          # 第02章 §3.3(p15)/§6.3.2(p56)
LLM_MAX_RETRIES = _env_int("LLM_MAX_RETRIES", 6)       # 第02章 §3.3(p15) 默认 6

# 摘要/压缩这类"辅助任务"单独给一个便宜模型名(第09章 §2.4.3 p34:摘要可用便宜模型)
LLM_CHEAP_MODEL = _env("LLM_CHEAP_MODEL", LLM_MODEL)


# ---------------------------------------------------------------- 降级备胎(第08章 §3.3 p53)
# ⚠️ 关键教训:备胎必须与主模型**不同源**。
#
# 我最初把备胎写成"同厂商的便宜模型"(即再取一次 LLM_MODEL),理由是"云上不该
# 回连开发机"。但实测这样**等于没有降级**:主备都用 DEEPSEEK_API_KEY,
# 而生产降级要应对的恰恰是"key 失效 / 余额不足 / 厂商故障"这类问题 ——
# 同一个 key 一坏,主备一起挂。
#   实测(坏 key 场景):
#     主=deepseek-chat(坏key) + 备=deepseek-chat(同一坏key) → 401 崩掉
#     主=deepseek-chat(坏key) + 备=Ollama qwen3:0.6b        → 兜住
#
# 所以备胎按下面的顺序解析,并且**允许显式关闭** —— "没有降级"比"假装有降级"诚实:
#   1) LLM_FALLBACK_PROVIDER 显式指定(cloud-other / ollama / none)
#   2) 若配了 LLM_FALLBACK_API_KEY(另一家厂商的 key)→ 用云端备胎,跨厂商真降级
#   3) 否则用本地 Ollama(免费、独立于云端,适合开发机;前提是 Ollama 在跑)
#   4) Ollama 也不可用 → 不挂 fallback 中间件,并在启动时打一条 warning
LLM_FALLBACK_PROVIDER = _env("LLM_FALLBACK_PROVIDER", "").lower()  # "" | ollama | cloud | none
LLM_FALLBACK_MODEL = _env("LLM_FALLBACK_MODEL", "")
LLM_FALLBACK_API_KEY = _env("LLM_FALLBACK_API_KEY")      # 另一家厂商的 key(跨厂商降级)
LLM_FALLBACK_BASE_URL = _env("LLM_FALLBACK_BASE_URL", "")

# ---------------------------------------------------------------- 本地 Ollama(第02章 §4.4 p24-25)
# 既是本地开发用的模型,也是默认的降级备胎(独立于云端,不受云端 key/余额影响)。
OLLAMA_BASE_URL = _env("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = _env("OLLAMA_MODEL", "qwen3:0.6b")


# ---------------------------------------------------------------- Embedding(第10章 §2.4.2 p48-49)
# 课件用云端 OpenAI 兼容网关(CloseAI 的 text-embedding-3-large / 硅基流动的 bge-m3),
# 第10章全程未使用 Ollama。所以 **cloud 是默认后端**,本地 Ollama 只作开发兜底。
#
# ✅ 实测结论(推翻了"本地/云端向量不通用"的猜测):
#    本机 Ollama 的 bge-m3 与硅基流动的 BAAI/bge-m3,对同一文本输出的向量
#    余弦相似度 **0.9999** —— 本项目里两者基本等价,可以互换使用,
#    **不需要因为换后端而重建知识库**。
#    (维度都是 1024,语义质量也一致:同义中文 0.991 / 无关 0.284。)
#    但仍建议:换 embedding **模型**(如换成 text-embedding-3-*)时必须重建。
#
# 用法:
#    EMBED_BACKEND=cloud(默认,课件路线)→ 需要 EMBED_API_KEY
#    EMBED_BACKEND=ollama            → 用本机 Ollama,无需 key,也不受云账户余额影响
#
# ⚠️ 云端有可用性风险,实测踩到:硅基流动账户余额不足时接口返回
#    402 / code 30001,而**在余额耗尽的临界状态下曾返回过严重降级的向量**
#    (同义中文相似度 0.27、向量间余弦仅 0.26),导致检索 Top1 命中率从 10/10
#    掉到 2/10 —— 而且不报错、静默给出垃圾排序。
#    因此:建库/评估前先确认云端可用;要稳定可复现就跑 EMBED_BACKEND=ollama。
EMBED_BACKEND = _env("EMBED_BACKEND", "cloud").lower()
EMBED_API_KEY = _env("EMBED_API_KEY")
EMBED_BASE_URL = _env("EMBED_BASE_URL", "https://api.siliconflow.cn/v1")
EMBED_MODEL = _env("EMBED_MODEL", "BAAI/bge-m3")
# 本地 Ollama 的 embedding 模型名与地址(第02章 §4.4 p24-25 的本地部署形态)
EMBED_OLLAMA_MODEL = _env("EMBED_OLLAMA_MODEL", "bge-m3")
# 是否在请求里带 dimensions 参数。
# ⚠️ 默认 **False**:实测硅基流动对 dimensions=1024 返回 400(code 20015),
#    而 bge-m3 本身输出就是 1024 维,无需该参数。
#    只有换成"支持并需要显式指定降维"的网关(如 OpenAI text-embedding-3-*)时才打开。
EMBED_SEND_DIMENSIONS = _env("EMBED_SEND_DIMENSIONS", "false").lower() == "true"

# langchain OpenAIEmbeddings 的 check_embedding_ctx_length 开关。
#
# ⚠️⚠️ 必须保持 **False**(本项目最严重的坑之一):
#    该参数默认 True,此时 OpenAIEmbeddings 会用 tiktoken 把文本切成
#    **token id 数组**再发给 API(源码:`self.client.create(input=batch_tokens, ...)`)。
#    这对 OpenAI 自家模型正常,但 bge-m3 这类非 OpenAI 模型会把一串整数当文本编码,
#    产出**语义错乱的向量且不报错**。
#
#    实测(本项目真实 P0 故障):打开时同义句相似度 0.27 反而低于无关句 0.60,
#    分数全挤在 0.60-0.71,"重修要交钱吗"返回奖学金/成绩复查/纪律申诉,
#    自查询召回不到自己(命中别的片段),检索命中率 **0/10**;
#    关掉后同义 0.9909、自查询 score 0.9999、命中率回到 **10/10**,
#    且与 Ollama 的 bge-m3 向量余弦 1.0000(两者本是同一向量空间,无需重建库)。
#
#    仅当你把 EMBED_MODEL 换成真正的 OpenAI embedding 模型时才需要改回 true。
EMBED_CHECK_CTX_LENGTH = _env("EMBED_CHECK_CTX_LENGTH", "false").lower() == "true"
# bge-m3 = 1024 维(第10章 §2.4.1 p47 模型表);Milvus collection 必须按这个维度建。
# 注意:Ollama 的 bge-m3 同样是 1024 维,所以两个后端可以共用同一个 collection 维度,
# 只是向量值不同 —— 这正是"必须重建"的原因。
EMBED_DIM = _env_int("EMBED_DIM", 1024)


# ---------------------------------------------------------------- Milvus(第10章 §2.5.3 p52-54)
MILVUS_URI = _env("MILVUS_URI", "http://localhost:19530")
MILVUS_DB_NAME = _env("MILVUS_DB_NAME", "campus_copilot")
MILVUS_COLLECTION = _env("MILVUS_COLLECTION", "xmum_policies")
MILVUS_METRIC = _env("MILVUS_METRIC_TYPE", "COSINE")   # 第10章 P53 metric_type="COSINE"

# 知识库后端:milvus(课件默认)| chroma(过渡,仅当 Milvus 尚未拉起时)
KB_BACKEND = _env("KB_BACKEND", "milvus").lower()
CHROMA_DIR = _env("CHROMA_DIR", "data/chroma_db")

# 检索参数(第10章 §2.5.3 p63-64 的 retrieve(question, k=5))
KB_TOP_K = _env_int("KB_TOP_K", 5)


# ---------------------------------------------------------------- 记忆后端(第09章 §2.2 p14-18)
# 课件 §2.2(p14-18)实操的是 PostgresSaver,故 postgres 是主路径;
# sqlite 留给"本地快速验证 / 无 PG 环境"(§2.1.3 p11 也把它列为合法选项)。
MEMORY_BACKEND = _env("MEMORY_BACKEND", "postgres")     # postgres | sqlite
# 本机 PostgreSQL 连接串；已有环境应在 .env 中显式配置自己的账号和数据库。
# 下方仅为历史开发默认值，不会创建数据库或迁移已有账号。
DATABASE_URL = _env(
    "DATABASE_URL", "postgresql://campus:campus_pw@127.0.0.1:5432/campus"
)
LOGIN_FAILURE_LIMIT = max(1, _env_int("LOGIN_FAILURE_LIMIT", 5))
LOGIN_FAILURE_WINDOW_SECONDS = max(1, _env_int("LOGIN_FAILURE_WINDOW_SECONDS", 900))
# SQLite 库路径(仅 sqlite 后端使用);留空则用项目根下的 data/memory.db
MEMORY_DB_PATH = _env("MEMORY_DB_PATH", "")


# ---------------------------------------------------------------- LangSmith(第03章 §2.3 p6)
# 课件列的是四个变量:TRACING / ENDPOINT / API_KEY / PROJECT
LANGSMITH_TRACING = _env("LANGSMITH_TRACING", "false").lower() == "true"
LANGSMITH_ENDPOINT = _env("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com")
LANGSMITH_API_KEY = _env("LANGSMITH_API_KEY")
LANGSMITH_PROJECT = _env("LANGSMITH_PROJECT", "campus-copilot")


# ---------------------------------------------------------------- Agent 运行参数
# 第07章 §4.4 问题6(p26):默认没有工具调用次数限制,超时/token 都可能出问题,
# 用 config={"recursion_limit": 5} 限制。
#
# ⚠️ 但 recursion_limit 用的是**图上节点数**语义,不是"工具调用轮数":
#    LangChain 1.x 把每个中间件钩子实现成一个独立节点(before_model / after_model),
#    所以本项目挂了 7 层中间件后,单次工具调用的开销被显著放大。
#    实测(measure_steps.py,项目自测脚本):
#        纯聊天(不调工具)      8 步
#        调用 1 个工具          26-35 步
#        调用 2 个工具          18 步
#    也就是说课件建议的 5、以及照字面理解的 12,在本项目的中间件栈下**连一次
#    工具调用都跑不完**(会抛 GraphRecursionError)。
#
#    因此 recursion_limit 这里**不是**主刹车,只作兜底(防真正失控);
#    真正的调用次数约束交给第08章 §3.1(p34)/§3.2(p44)的两个中间件:
#        ModelCallLimitMiddleware / ToolCallLimitMiddleware
#    它们的计数与图节点数无关,语义更贴近"调用次数"。
RECURSION_LIMIT = _env_int("RECURSION_LIMIT", 100)
# 工具调用/模型调用上限(第08章 §3.1 p34、§3.2 p44)
# ⚠️ 语义实测(课件未讲清,踩过坑):
#    `thread_limit` 是**按会话累计**的上限,不是"每轮"。它把计数存在
#    state["thread_model_call_count"] 里,由 checkpointer 持久化,所以
#    一个 thread 上的多轮对话会累加。一旦触顶且 exit_behavior="end",
#    该会话后续每一轮都会被**立即结束** —— 实测表现为模型不再输出任何内容、
#    回答变成空字符串(size=0),而且不报错。
#    本项目有"持久化多用户会话",长对话很常见:一轮问答通常 2-3 次模型调用,
#    所以 30 对"一个会话聊 10 轮"就会误伤。这里放宽到 200 作为成本兜底。
#    单轮的失控保护交给 recursion_limit(见上方说明),
#    两者分工不同:recursion_limit 管"一次运行跑多久",thread_limit 管"一个会话总共花多少"。
TOOL_CALL_THREAD_LIMIT = _env_int("TOOL_CALL_THREAD_LIMIT", 200)
MODEL_CALL_THREAD_LIMIT = _env_int("MODEL_CALL_THREAD_LIMIT", 200)
# 摘要触发阈值(第08章 §2.1 p7-11 / 第09章 §2.4.3 p31-34)
SUMMARY_TRIGGER_MESSAGES = _env_int("SUMMARY_TRIGGER_MESSAGES", 30)
SUMMARY_TRIGGER_TOKENS = _env_int("SUMMARY_TRIGGER_TOKENS", 24000)
SUMMARY_KEEP_MESSAGES = _env_int("SUMMARY_KEEP_MESSAGES", 10)

# 上下文编辑(第08章 §3.8 p73;默认不启用,见 middleware.get_context_editing 的实测说明)
# ⚠️ trigger 的单位是 **token**,不是消息条数。初版误设 50 + keep=0,
#    导致工具结果在模型作答前被清空 → 模型回答"画像是空的"(实测)。
CONTEXT_EDIT_TRIGGER_TOKENS = _env_int("CONTEXT_EDIT_TRIGGER_TOKENS", 100000)
CONTEXT_EDIT_KEEP_TOOL_RESULTS = _env_int("CONTEXT_EDIT_KEEP_TOOL_RESULTS", 3)
