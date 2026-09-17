"""M4:记忆层 —— 短期会话 + 长期画像,统一入口。

两层记忆的分工(LangGraph 的标准架构):
- checkpointer(短期):按 thread_id 存整个会话的消息状态。
  重启进程后同 thread_id 能续聊;不同 thread_id 互不可见。
  M3 已用 InMemorySaver 占位,本模块换成落盘的持久化实现。
- store(长期):按 namespace 存键值(用户画像)。
  key 形如 ("profiles", user_id),跨 thread、跨会话都在。
  "我是大几的""我常问什么"这类问题靠它回答。

后端选择:
- sqlite(默认):零基建,开发期用。checkpointer 与 store 共用一个文件。
- postgres:M6 Docker Compose 上线后切换,只改 MEMORY_BACKEND 环境变量,
  两套实现都是 langgraph 同一接口(BaseCheckpointSaver / BaseStore),
  业务代码零改动 —— 这就是"面向接口编程"的回报。
"""
import os
from contextlib import ExitStack
from pathlib import Path

DB_PATH = Path("data") / "memory.db"

# 模块级 ExitStack:连接随进程存活,退出时统一关闭
_stack = ExitStack()


def get_checkpointer():
    """短期记忆:会话状态持久化。"""
    backend = os.environ.get("MEMORY_BACKEND", "sqlite")
    if backend == "postgres":
        from langgraph.checkpoint.postgres import PostgresSaver

        saver = _stack.enter_context(
            PostgresSaver.from_conn_string(os.environ["DATABASE_URL"])
        )
    else:
        from langgraph.checkpoint.sqlite import SqliteSaver

        DB_PATH.parent.mkdir(exist_ok=True)
        saver = _stack.enter_context(
            SqliteSaver.from_conn_string(str(DB_PATH))
        )
    saver.setup()  # 首次建表,幂等
    return saver


def get_store():
    """长期记忆:用户画像(年级/专业/关注话题),跨会话保留。"""
    backend = os.environ.get("MEMORY_BACKEND", "sqlite")
    if backend == "postgres":
        from langgraph.store.postgres import PostgresStore

        store = _stack.enter_context(
            PostgresStore.from_conn_string(os.environ["DATABASE_URL"])
        )
    else:
        from langgraph.store.sqlite import SqliteStore

        DB_PATH.parent.mkdir(exist_ok=True)
        store = _stack.enter_context(
            SqliteStore.from_conn_string(str(DB_PATH))
        )
    store.setup()
    return store


def reset_memory() -> None:
    """清空记忆数据库(测试用)。生产环境绝不调用。"""
    if DB_PATH.exists():
        DB_PATH.unlink()
