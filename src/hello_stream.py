"""M0 验证脚本:DeepSeek 模型的 invoke 与 stream 两种调用方式。

运行(项目根目录):.venv\\Scripts\\python src\\hello_stream.py
课程对应:P12(调用 DeepSeek 官网模型)、P21(流式调用)
"""
import os

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

# 1. 加载 .env 环境变量(密钥不硬编码,永不进入代码和 git)
load_dotenv()

# 2. 初始化模型:DeepSeek 兼容 OpenAI 接口,所以用 ChatOpenAI + base_url 指向 DeepSeek
llm = ChatOpenAI(
    api_key=os.environ["DEEPSEEK_API_KEY"],
    base_url=os.environ["DEEPSEEK_BASE_URL"],
    model="deepseek-chat",  # V3 对话模型;deepseek-reasoner 为推理模型
)

# ---- 方式一:invoke,一次性返回完整回答 ----
print("=== invoke(一次性返回)===")
resp = llm.invoke("用一句话说明什么是大语言模型")
print(resp.content)

# ---- 方式二:stream,逐块输出(打字机效果)----
print("\n=== stream(流式返回)===")
for chunk in llm.stream("用三句话介绍 LangChain 框架"):
    print(chunk.content, end="", flush=True)

print("\n\n=== M0 第 3 项验证通过:模型调用与流式输出正常 ===")
