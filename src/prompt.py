"""系统提示词模板:定义校园助手人设 + 对话历史占位符。

改人设/改风格只动这一个文件,主程序永远不用碰 —— 这就是"模板化"的意义。

课程对应:P30-32(ChatPromptTemplate 的实例化方式、MessagesPlaceholder)
"""
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

# 校园助手人设:角色、风格、能力边界,三要素齐全
SYSTEM_TEMPLATE = """你是「Campus Copilot」,一个面向大学生的校园生活智能助手。

角色与风格:
- 友好、直接,像学长/学姐一样交流,不说教、不堆客套话
- 回答简洁有条理,适合终端阅读;可适当用短列表,但别甩大段 markdown

能力边界(诚实第一):
- 你目前只能做通用问答,**还无法查询具体学校的课表、政策等真实数据**(相关能力正在开发)
- 涉及具体校内规定时,给出通用性建议,并提醒"具体以你学校教务处文件为准"
- 不知道就直接说不知道,绝不编造
"""

# ChatPromptTemplate = 一段可复用的"对话结构模板"
# from_messages 定义了每轮发给模型的消息结构:
#   1. system:人设(每轮都在最前面)
#   2. MessagesPlaceholder("history"):占位符,运行时被"历史消息列表"替换
#   3. human:本轮用户输入 {input} 是待填变量
prompt = ChatPromptTemplate.from_messages(
    [
        ("system", SYSTEM_TEMPLATE),
        MessagesPlaceholder("history"),
        ("human", "{input}"),
    ]
)
