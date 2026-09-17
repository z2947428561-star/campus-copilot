"""长期记忆工具:读写用户画像(M4)。

课程对应:P96-101(Store、跨会话记忆、工具内读写记忆)。

机制说明:
- store 由 create_agent(store=...) 注入运行时;
- 工具函数体内用 get_store() / get_config() 从运行时上下文里取,
  这两个是 langgraph 提供的"上下文钩子",和 LCEL 的 runnable_config 同族;
- 用户身份从 config["configurable"]["user_id"] 拿(CLI 启动时传入),
  画像命名空间 ("profiles", user_id) 因此按用户隔离。
"""
from langchain_core.tools import tool
from langgraph.config import get_config, get_store


def _current_user() -> str:
    """从运行时配置取当前用户,取不到则归为 default。"""
    try:
        cfg = get_config() or {}
        return cfg.get("configurable", {}).get("user_id", "default")
    except Exception:
        return "default"


def _try_store():
    """拿到 store 则返回,运行时没挂 store(如 M2 裸 CLI)则返回 None。"""
    try:
        return get_store()
    except Exception:
        return None


@tool
def save_profile(key: str, value: str) -> dict:
    """把用户的长期信息写入画像(跨会话保留,永久记住)。

    适用于用户透露:年级、专业、在读课程、目标(如考研/就业)、
    个人偏好(如"我喜欢下午自习")、常关注的话题等。
    同一个 key 再次写入会覆盖更新。

    Args:
        key: 画像字段名,英文小写,如 grade / major / courses / goal / interests
        value: 字段内容,中文短语,如 "大一" / "计算机科学" / "选课、空教室"
    """
    store = _try_store()
    if store is None:
        return {"ok": False, "error": "长期记忆未启用(需要 store)"}

    user = _current_user()
    store.put(("profiles", user), key, {"value": value})
    return {"ok": True, "user": user, "key": key, "value": value}


@tool
def read_profile() -> dict:
    """读取当前用户的完整长期画像(年级、专业、关注话题等)。

    回答个性化问题前先调用:如「我是大几的」「我什么专业」「我常问什么」。
    """
    store = _try_store()
    if store is None:
        return {"ok": False, "error": "长期记忆未启用(需要 store)"}

    user = _current_user()
    items = store.search(("profiles", user))
    profile = {item.key: item.value.get("value") for item in items}
    return {"ok": True, "user": user, "profile": profile}
