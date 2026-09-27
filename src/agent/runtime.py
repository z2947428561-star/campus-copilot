"""Agent 运行配置与 LangSmith 追踪的统一入口。

课程对应:
    第02章 §6.4(p62-65) config 参数:run_name / tags / metadata / recursion_limit
        —— 课件原文:"init 是默认设置,config 是单次调用且优先级更高"
    第03章 §3 举例3(p7-8) 给 config 带 run_name / tags / metadata{user_id, session_id},
        这样在 LangSmith 的 WebUI 里能按用户/会话筛选
    第07章 §4.4 问题6(p26) config={"recursion_limit": 5} 限制工具调用步数,
        否则默认没有限制,可能超时或撞 token 上限
    第03章 §2.3(p6)      LangSmith 的四个环境变量

为什么集中:
    旧版每个入口各写一段 cfg,只有 configurable 两个键:
        {"configurable": {"thread_id": ..., "user_id": ...}}
    既没有 recursion_limit(第07章 p26 明确要求),也没有 run_name/tags/metadata
    (第02章 p62-65、第03章 p7-8),导致 LangSmith 里无法按用户或评估轮次筛选 trace。
"""
import logging
import os

import config

logger = logging.getLogger("campus")

__all__ = ["setup_langsmith", "make_config", "default_thread_id"]


def setup_langsmith() -> None:
    """把 LangSmith 的四个环境变量补齐(第03章 §2.3 p6)。

    课件列的是四个变量:
        LANGSMITH_TRACING / LANGSMITH_ENDPOINT / LANGSMITH_API_KEY / LANGSMITH_PROJECT
    旧版三处配置都缺 LANGSMITH_ENDPOINT。

    注意:必须在创建 agent、发起调用之前调用本函数 ——
    LangSmith SDK 在导入/首次调用时读取这些环境变量。
    """
    os.environ["LANGSMITH_TRACING"] = "true" if config.LANGSMITH_TRACING else "false"
    os.environ["LANGSMITH_ENDPOINT"] = config.LANGSMITH_ENDPOINT
    os.environ["LANGSMITH_PROJECT"] = config.LANGSMITH_PROJECT
    if config.LANGSMITH_API_KEY:
        os.environ["LANGSMITH_API_KEY"] = config.LANGSMITH_API_KEY

    if config.LANGSMITH_TRACING and not config.LANGSMITH_API_KEY:
        logger.warning(
            "[LangSmith] 开启了 tracing 但没有 LANGSMITH_API_KEY,上报会失败。"
            "请在 .env 补上,或把 LANGSMITH_TRACING 设为 false。"
        )
    elif config.LANGSMITH_TRACING:
        logger.info("[LangSmith] tracing 已开启,project=%s", config.LANGSMITH_PROJECT)


def default_thread_id(user_id: str, suffix: str = "main") -> str:
    """会话 id 约定:每个用户一条主会话。

    第09章 §2.1.3(p11)的两条场景:
        多用户隔离 → thread_id="user_alice" / "user_bob"
        同用户多任务 → thread_id="task_coding" / "task_docs"
    这里用 f"{user_id}-{suffix}",suffix 可用来开新话题(如 "new-topic")。
    """
    return f"{user_id}-{suffix}"


def make_config(
    *,
    thread_id: str,
    user_id: str,
    run_name: str | None = None,
    tags: list[str] | None = None,
    recursion_limit: int | None = None,
) -> dict:
    """构造 agent.stream / invoke 的 config。

    run_name / tags / metadata 只影响 LangSmith 的可读性(第03章 §3 p7-8),
    不影响推理行为;recursion_limit 才是行为约束(第07章 §4.4 p26)。
    """
    cfg: dict = {
        "configurable": {
            "thread_id": thread_id,
            # user_id 保留在 configurable 里只为兼容旧调用与短期会话;
            # 画像读写已改为走 context_schema(见 src/context.py),不再从这里取。
            "user_id": user_id,
        },
        "recursion_limit": recursion_limit or config.RECURSION_LIMIT,
    }
    if run_name:
        cfg["run_name"] = run_name
    if tags:
        cfg["tags"] = tags
    cfg["metadata"] = {"user_id": user_id, "thread_id": thread_id}
    return cfg
