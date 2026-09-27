"""M1 专用提示词模板:ChatPromptTemplate + MessagesPlaceholder。

课程对应:
    第04章 §2.3.1(p28-30) ChatPromptTemplate 的两种实例化方式(方式1 from_messages 推荐)
    第04章 §2.4.2(p38-40) MessagesPlaceholder —— 课件给的用途正是
                          "多轮对话系统存储历史消息"
    第04章 §2.3.2(p30-31) format() 返回带角色前缀的字符串,取消息要用 format_messages()

与旧版的差异(重要:这里原本有两个人设互相矛盾):
    旧版本文件里另写了一份人设,内容是"你目前只能做通用问答,**还无法查询
    具体学校的课表、政策等真实数据**(相关能力正在开发)";
    而 Agent 版(agent/assistant.py)要求"教务政策问题必须先调 search_policy
    检索官方手册原文"。同一产品的两个入口给了相反的能力口径 ——
    第04章 §1.2(p2)说系统消息"决定其回答问题的风格、领域和专业范围",
    两处不一致就是产品级 bug。

    现在文案统一从 prompts 包导出,本文件只负责"M1 的模板结构"。

适用范围:
    M1 的 chat_cli.py 用本文件的 prompt(手工维护历史 + MessagesPlaceholder)。
    M2 之后历史由 checkpointer 托管、人设由 create_agent(system_prompt=...) 注入,
    不再经过本文件(第09章 §2.1.2 p7-8)。
"""
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from prompts import FIXED_VARS, PERSONA, STYLE

# M1 是"通识对话"阶段的教学版本:只用人设 + 风格 + 诚实底线。
# 工具纪律 / 引用纪律那时还不成立(还没有工具与知识库),由 prompts.system 按阶段注入。
from prompts.common import HONESTY

SYSTEM_TEMPLATE = "\n\n".join([PERSONA, STYLE, HONESTY]).format(
    school=FIXED_VARS["school"]
)

# ChatPromptTemplate = 一段可复用的"对话结构模板"
# from_messages 定义了每轮发给模型的消息结构:
#   1. system:人设(每轮都在最前面)
#   2. MessagesPlaceholder("history"):占位符,运行时被"历史消息列表"替换
#   3. human:本轮用户输入(变量 {input})
prompt = ChatPromptTemplate.from_messages(
    [
        ("system", SYSTEM_TEMPLATE),
        MessagesPlaceholder("history"),
        ("human", "{input}"),
    ]
)
