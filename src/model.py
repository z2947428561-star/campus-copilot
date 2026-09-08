"""模型工厂:统一创建对话模型实例。

为什么要抽出来:hello_stream.py 里的初始化代码,M2 的 Agent、M3 的
中间件都要用。集中一处,以后换模型/换平台只改这一个函数。

课程对应:P11-17(模型调用准备、初始化参数)
"""
import os

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()  # 从 .env 加载密钥(不硬编码,永不入库)


def get_chat_model(model_name: str = "deepseek-chat") -> ChatOpenAI:
    """返回 DeepSeek 对话模型实例。

    model_name:
        deepseek-chat     —— V3 对话模型,日常对话用它(快、便宜)
        deepseek-reasoner —— R1 推理模型,复杂推理任务再用(慢、贵)
    """
    return ChatOpenAI(
        api_key=os.environ["DEEPSEEK_API_KEY"],
        base_url=os.environ["DEEPSEEK_BASE_URL"],
        model=model_name,
    )
