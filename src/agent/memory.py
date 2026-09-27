"""记忆层:短期会话 + 长期画像,统一入口。

课程对应(第09章《上下文与记忆》):
    §1.2.2(p5)     上下文类型与相关 API:动态运行时=state / 动态跨会话=store /
                   静态运行时=context
    §2.1(p6-13)    短期记忆三件套:State + Checkpointer + Thread ID
    §2.1.3(p11)    关键步骤说明:同 thread_id 共享、异 thread_id 完全隔离;
                   课件原文"生产环境可换成数据库持久化的 SqliteSaver、PostgresSaver 等"
    §2.2(p14-18)   基于外部存储介质的持久化器 —— **课件实操的是 PostgresSaver**,
                   `with PostgresSaver.from_conn_string(DB_URL) as checkpointer:
                   checkpointer.setup()`,并展示了 setup 建出的表
    §2.3(p18-24)   两种方式对比:InMemorySaver 进程结束即丢;外部介质靠 thread_id 可加载
    §3.1.3(p39-41) store → namespace → key → value 四层结构
    §3.2(p41-52)   put / get / search
    §4.2(p74-80)   context 注入(用户身份不由本模块管,见 src/context.py)

两层记忆的分工:
    checkpointer(短期)按 thread_id 存整个会话状态;同 thread_id 重启后续聊。
    store(长期)按 namespace 存键值,namespace = ("profiles", user_id),跨 thread 都在。

后端选择(按课件):
    **postgres 是主路径**(课件 §2.2 p14-18 实操它),`.env` 的 MEMORY_BACKEND=postgres。
    sqlite 保留给"本地快速验证/无 PG 环境"(课件 §2.1.3 p11 也把 SqliteSaver 列为
    合法的生产选项之一,但第09章的代码实操没有演示它)。

连接生命周期(与旧版的差异):
    旧版用模块级 `ExitStack` 长期持有连接,但**全项目没有一处 close** ——
    没有优雅停机,异常路径下连接会一直挂到进程退出。
    现在:
      - 仍用 ExitStack 缓存(Agent 是进程内单例,需要跨请求复用连接),
      - 但提供 `close_memory()`,由 `src/server.py` 的 lifespan 与测试脚本显式调用。
    SqliteSaver/SqliteStore/PostgresSaver/PostgresStore 的 `from_conn_string`
    实测**都是上下文管理器**,所以"进程级长连接"本质是把 with 的生存期拉长到进程级,
    必须配套显式 close 才成立。

数据库文件位置(与旧版的差异):
    旧版 `DB_PATH = Path("data") / "memory.db"` 是**相对路径**,相对的是进程 CWD。
    从别的目录启动会静默新建第二个空库(表现为"记忆突然全丢")。
    现在改为项目根下的绝对路径(由 `__file__` 推导),并支持 `MEMORY_DB_PATH` 覆盖
    —— 后者让测试可以用临时库,而不是删生产库(见 scripts/test_m4.py)。
"""
import logging
import os
from contextlib import ExitStack
from pathlib import Path

import config

logger = logging.getLogger("campus")

# 项目根 = src/agent/memory.py 的上两级
_ROOT = Path(__file__).resolve().parents[2]

# 兼容旧引用:scripts/test_m4.py 曾 `from agent.memory import DB_PATH`
# 路径优先取 config.MEMORY_DB_PATH(测试可注入临时库),否则用项目根下的 data/memory.db
DB_PATH = Path(config.MEMORY_DB_PATH) if config.MEMORY_DB_PATH else (_ROOT / "data" / "memory.db")

# 模块级 ExitStack:连接随进程存活,退出/测试收尾时由 close_memory() 统一关闭
_stack = ExitStack()

# 缓存已建好的实例:同一进程内多个 agent 实例应当共享同一个 checkpointer/store
_cache: dict[str, object] = {}


def _backend() -> str:
    return (config.MEMORY_BACKEND or "sqlite").lower()


def get_checkpointer():
    """短期记忆:会话状态持久化(第09章 §2.1-§2.2)。"""
    if "checkpointer" in _cache:
        return _cache["checkpointer"]

    backend = _backend()
    if backend == "postgres":
        from langgraph.checkpoint.postgres import PostgresSaver

        if not config.DATABASE_URL:
            raise RuntimeError(
                "MEMORY_BACKEND=postgres 但没有配置 DATABASE_URL。"
                "请在 .env 里设置,例如:"
                "DATABASE_URL=postgresql://campus:campus_pw@127.0.0.1:5432/campus"
            )
        # 课件 §2.2(p15)的写法:with PostgresSaver.from_conn_string(...) as checkpointer
        saver = _stack.enter_context(
            PostgresSaver.from_conn_string(config.DATABASE_URL)
        )
    else:
        from langgraph.checkpoint.sqlite import SqliteSaver

        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        saver = _stack.enter_context(SqliteSaver.from_conn_string(str(DB_PATH)))

    saver.setup()  # 首次建表,幂等(课件 §2.2.2 p16)
    logger.info("[记忆] checkpointer 就绪 backend=%s", backend)
    _cache["checkpointer"] = saver
    return saver


def get_store():
    """长期记忆:用户画像,跨会话保留(第09章 §3)。"""
    if "store" in _cache:
        return _cache["store"]

    backend = _backend()
    if backend == "postgres":
        from langgraph.store.postgres import PostgresStore

        if not config.DATABASE_URL:
            raise RuntimeError(
                "MEMORY_BACKEND=postgres 但没有配置 DATABASE_URL(见 .env)"
            )
        # 课件 §3.2(p44):with PostgresStore.from_conn_string(DB_URL) as store: store.setup()
        store = _stack.enter_context(
            PostgresStore.from_conn_string(config.DATABASE_URL)
        )
    else:
        from langgraph.store.sqlite import SqliteStore

        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        store = _stack.enter_context(SqliteStore.from_conn_string(str(DB_PATH)))

    store.setup()
    logger.info("[记忆] store 就绪 backend=%s", backend)
    _cache["store"] = store
    return store


def close_memory() -> None:
    """释放连接(优雅停机/测试收尾)。

    旧版没有这个函数,ExitStack 从不 close —— 进程退出前连接一直挂着。
    调用方:src/server.py 的 FastAPI lifespan、scripts/test_m4.py 的 finally。
    可重复调用(ExitStack.close 幂等)。
    """
    _cache.clear()
    try:
        _stack.close()
    except Exception as e:  # noqa: BLE001
        logger.warning("[记忆] 关闭连接时出错: %r", e)


def reset_memory() -> None:
    """清空本地 SQLite 记忆库(仅供测试)。

    ⚠️ 只对 sqlite 后端有意义,且**必须先 close_memory()**:
    SQLite 开了 WAL,连接还开着时删主库文件会留下 memory.db-wal / -shm 残留
    (这正是旧版把 4.1MB 的 memory.db-wal 提交进 git 的原因之一)。
    生产环境(尤其是 postgres)绝不调用。
    """
    if _backend() == "postgres":
        raise RuntimeError("reset_memory() 不支持 postgres 后端,请手动清表或换库")
    close_memory()
    for suffix in ("", "-wal", "-shm"):
        f = Path(str(DB_PATH) + suffix)
        if f.exists():
            try:
                f.unlink()
                logger.info("[记忆] 已删除 %s", f.name)
            except OSError as e:
                logger.warning("[记忆] 删除 %s 失败: %r", f.name, e)
