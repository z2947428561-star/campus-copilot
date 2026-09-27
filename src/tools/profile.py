"""长期记忆工具:读写用户画像。

课程对应:
    第09章 §3.1.3(p39-41) store → namespace → key → value 四层结构
    第09章 §3.2(p41-52)   put / get / search 基础 API
    第09章 §3.3.1(p52-56) 工具中访问长期记忆
    第09章 §4.2(p74-80)   context 注入版(本文件采用)
    第05章 §3.1(p16-18)   parse_docstring
    第05章 §6.4(p43)      工具返回字符串

与旧版的差异(为什么改):
1) 身份来源:`get_config()["configurable"]["user_id"]` → `runtime.context.user_id`。
   第09章 §4 全篇教 context_schema / ToolRuntime,而 get_store()/get_config()
   在整章 6303 行里零出现 —— 旧版 docstring 自称"课程对应 P96-101"并不成立
   (该页码也不属于第09章:本章实际覆盖 P38-P80)。
2) 去掉 "default" 兜底:见 context.py 的说明,那是一条约实的跨用户泄漏路径。
3) 返回值改为字符串(第05章 §6.4 p43:"工具应返回字符串")。
4) store 缺失时不再静默,而是明确回报 —— 第09章 §4.2(p77)的示范是
   try/except + logger.error + 返回失败标志,不是 pass。
"""
import json
import logging

from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime

from context import UserContext

logger = logging.getLogger("campus")

# namespace 约定:("profiles", user_id)
# 第09章 §3.1.3(p40):namespace 是 tuple 层级路径,用于分组与隔离。
# key 用字段名(grade/major/interests/...),比"整个 dict 一个 key"更抗并发覆盖。
NAMESPACE_ROOT = "profiles"


def _dump(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _namespace(user_id: str) -> tuple[str, ...]:
    return (NAMESPACE_ROOT, user_id)


def _context_error(runtime: ToolRuntime[UserContext]) -> str | None:
    """校验 context 里的用户身份。

    第09章 §4.2(p74-80)的精神:身份由调用方显式传入。
    这里再挡一道 —— 空 user_id 会落进 ("profiles","") 这个共享命名空间,
    等于把旧的 "default" 泄漏路径换个名字保留,所以必须拒绝。
    """
    if runtime.context is None:
        return "调用时未传 context,无法确定用户身份"
    if not (runtime.context.user_id or "").strip():
        return "context.user_id 为空,拒绝读写画像(避免所有匿名用户互相看到对方的画像)"
    return None


@tool(
    parse_docstring=True,
    description=(
        "把用户的长期信息写入画像(跨会话保留,永久记住)。"
        "适用于用户透露:年级、专业、在读课程、目标(如考研/就业)、"
        "个人偏好(如「我喜欢下午自习」)、常关注的话题等。"
        "同一个 key 再次写入会覆盖更新。"
    ),
)
def save_profile(key: str, value: str, runtime: ToolRuntime[UserContext]) -> str:
    """写入一条长期画像字段。

    Args:
        key: 画像字段名,英文小写,如 grade / major / courses / goal / interests。
        value: 字段内容,中文短语,如「大一」「计算机科学」「选课、空教室」。

    Returns:
        操作结果的 JSON 字符串(ok/user/key/value);store 未挂载时
        返回 ok=false 与原因。
    """
    store = runtime.store
    if store is None:
        # 第09章 §4.2(p77):不静默,明确回报失败原因
        return _dump({"ok": False, "error": "长期记忆未启用(Agent 创建时未挂 store)"})
    if (err := _context_error(runtime)):
        return _dump({"ok": False, "error": err})

    user_id = runtime.context.user_id
    store.put(_namespace(user_id), key, {"value": value})
    # 写入记一条日志,便于排查(第09章 §4.2 p77 的同款做法)
    logger.info("[画像] 写入 user=%s key=%s value=%s", user_id, key, value)
    return _dump({"ok": True, "user": user_id, "key": key, "value": value})


@tool(
    parse_docstring=True,
    description=(
        "读取当前用户的完整长期画像(年级、专业、关注话题等)。"
        "回答个性化问题前先调用,如「我是大几的」「我什么专业」「我常问什么」。"
    ),
)
def read_profile(runtime: ToolRuntime[UserContext]) -> str:
    """读取当前用户的全部长期画像字段。

    Returns:
        画像内容的 JSON 字符串(ok/user/profile);画像为空时 profile 为空对象,
        store 未挂载时返回 ok=false 与原因。
    """
    store = runtime.store
    if store is None:
        return _dump({"ok": False, "error": "长期记忆未启用(Agent 创建时未挂 store)"})
    if (err := _context_error(runtime)):
        return _dump({"ok": False, "error": err})

    user_id = runtime.context.user_id
    items = store.search(_namespace(user_id))
    profile = {item.key: (item.value or {}).get("value") for item in items}
    return _dump({"ok": True, "user": user_id, "profile": profile})
