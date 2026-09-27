"""运行时上下文:用户身份等"运行级静态配置"。

课程对应:第09章 §4(p60-80)"Static runtime Context"

课件原话:context 是"不可变数据,如用户元数据、工具、DB 连接对象",
"运行开始时通过 invoke/stream 的 context 参数传入,运行期间不变"。

为什么从 configurable 改成 context(旧版的问题):
    旧版在工具里用 `get_config()["configurable"]["user_id"]` 取用户身份,
    并在取不到时兜底成 "default"(见旧 profile.py:20)。这构成一条真实的
    跨用户数据泄漏路径:任何未带 user_id 的调用(裸测试、第三方 HTTP)
    都会把画像写进共享的 ("profiles","default"),读取时也会把别人写的
    内容读出来。

    第09章 §4.2(p74-80)的做法是:身份必须由调用方显式传入,
    工具通过 ToolRuntime 拿 —— 要么给、要么报错,不存在"静默落到 default"。

课件另外提醒(p80 第 5 条):
    工具里要用 `ToolRuntime[UserContext, Any]` **显式给出第一个泛型**,
    否则底层认为 context 是 None,传 context 时会告警。
"""
from dataclasses import dataclass


@dataclass
class UserContext:
    """运行级不可变身份:每次 invoke/stream 由调用方显式传入。

    user_id 同时用作:
      - 长期记忆的 namespace 维度:("profiles", user_id)
      - 短期会话的 thread_id 前缀(由调用方拼,如 f"{user_id}-main")
      - LangSmith trace 的 metadata(第03章 §3 举例3 p7-8)
    """

    user_id: str
