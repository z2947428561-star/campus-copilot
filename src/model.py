"""模型工厂:统一创建对话模型实例(第02章《模型的创建与调用》)。

课程对应:
    第02章 §1.2(p1-2)   三个初始化角度:谁家 API / 参数写哪 / 模型在哪
    第02章 §2.2(p8)     兼容写法 —— 大多数平台支持 OpenAI 规范,可用 ChatOpenAI 统一接入
    第02章 §3(p11-13)   init_chat_model 是 LangChain 1.x 的统一入口(课件推荐)
    第02章 §3.3(p15-16)  temperature / max_tokens / timeout / max_retries 的取值与分档
    第02章 §4.4(p24-25) 本地模型(Ollama)
    第02章 §6.2(p50-53) profile 能力画像(排查"备胎模型支不支持工具调用")
    第02章 §6.4(p62-65) configurable_fields:运行时覆盖 model / temperature / max_tokens

与旧版的差异(为什么改):
- 旧版直接 new ChatOpenAI,参数只有三个;课件 §3.3 明确要求的
  temperature / max_tokens / timeout / max_retries 全部缺失。
- 旧版把"换模型"说成"只改这一个函数",但实际换平台要改代码;
  现在走 init_chat_model + provider 表,换平台只改 .env(课件 §3 的"易于切换")。
- temperature:课件 §3.3(p15-16)指出 0.0-0.3 适合数学计算/数据提取/分类/代码生成。
  本项目是"抽取事实 + 算 GPA + 路由工具",所以默认 0.2 而不是课件的 0.7 默认值。

注意一处刻意的取舍:
    课件 §2.1.1(p4-6)演示了 DeepSeek 官方库 `ChatDeepSeek(api_key=.., api_base=..)`,
    但 model_provider="deepseek" 需要额外安装 langchain-deepseek 包。
    为了不引入新依赖,默认走 §2.2(p8) 的 OpenAI 兼容写法(功能等价);
    装了 langchain-deepseek 后,把 .env 的 LLM_PROVIDER 改成 deepseek 即可切到官方库。
"""
import logging

from langchain.chat_models import init_chat_model
from langchain_openai import ChatOpenAI

import config

logger = logging.getLogger("campus")


def _provider_kwargs(provider: str) -> dict:
    """按 provider 组装连接参数(第02章 §1.2 角度1:调用谁家的 API)。"""
    if provider == "deepseek":
        # 第02章 §2.1.1(p4):DeepSeek 官方库,参数名是 api_base(不是 base_url)
        return {
            "model_provider": "deepseek",
            "api_key": config.LLM_API_KEY,
            "api_base": config.LLM_BASE_URL,
        }
    if provider == "ollama":
        # 第02章 §4.4(p24-25):本地模型。这里用 OpenAI 兼容 /v1 接入,
        # 与 §2.2(p8) 的兼容思路一致;Ollama 的 /v1 不校验 key,填占位符。
        return {
            "model_provider": "openai",
            "api_key": "ollama",
            "base_url": config.OLLAMA_BASE_URL.rstrip("/") + "/v1",
        }
    # 默认:OpenAI 兼容网关(DeepSeek 官网 / CloseAI / 硅基流动 / OpenRouter 都适用)
    return {
        "model_provider": "openai",
        "api_key": config.LLM_API_KEY,
        "base_url": config.LLM_BASE_URL,
    }


def get_chat_model(model_name: str | None = None, provider: str | None = None):
    """返回主对话模型实例(LangChain 统一入口 init_chat_model)。

    model_name:
        None                → 读 .env 的 LLM_MODEL(默认 deepseek-chat)
        "deepseek-chat"     —— V3 对话模型,日常对话用它(快、便宜)
        "deepseek-reasoner" —— R1 推理模型,复杂推理再用(慢、贵)
    provider:
        None → 读 .env 的 LLM_PROVIDER(默认 openai 兼容网关)
    """
    provider = provider or config.LLM_PROVIDER
    model_name = model_name or config.LLM_MODEL

    if provider != "ollama" and not config.LLM_API_KEY:
        # 第02章 §5.5(p47):把裸 KeyError 换成带指引的报错
        raise RuntimeError(
            "缺少 DEEPSEEK_API_KEY。请在项目根目录创建 .env(参考 .env.example),"
            "或确认当前工作目录就是项目根目录。"
        )

    return init_chat_model(
        model=model_name,
        temperature=config.LLM_TEMPERATURE,      # §3.3(p15-16)
        max_tokens=config.LLM_MAX_TOKENS,        # §3.3(p15)
        timeout=config.LLM_TIMEOUT,              # §3.3(p15)/§6.3.2(p56)
        max_retries=config.LLM_MAX_RETRIES,      # §3.3(p15) 默认 6
        # §6.4(p64-65):只有声明了 configurable_fields,才能在运行时用
        # config={"configurable": {...}} 覆盖这些参数(评估/AB 实验很有用)
        configurable_fields=("model", "temperature", "max_tokens"),
        **_provider_kwargs(provider),
    )


def get_cheap_model():
    """辅助任务专用模型(摘要/压缩)。

    第09章 §2.4.3(p34):摘要可交给便宜模型,并提醒"摘要会让成本翻倍"。
    默认与主模型同名(DeepSeek 对话模型本身就是低价档);
    若配了 LLM_CHEAP_MODEL,则单独使用。
    """
    return get_chat_model(model_name=config.LLM_CHEAP_MODEL)


def get_fallback_model():
    """降级备胎模型。

    第08章 §3.3(p53)ModelFallbackMiddleware 的备胎。

    ⚠️ 备胎必须与主模型**不同源**(见 config.py 里的说明):
       主备共用同一个 DEEPSEEK_API_KEY 时,key 失效 / 余额不足会让两者一起挂,
       等于没有降级 —— 而这恰恰是降级机制要应对的场景。
       实测:坏 key 下"备胎=同厂商模型"直接 401 崩掉;备胎=Ollama 才兜住。

    解析顺序:
      1) LLM_FALLBACK_PROVIDER=cloud 且配了 LLM_FALLBACK_API_KEY
         → 另一家厂商的云端模型(跨厂商真降级,云部署推荐)
      2) 否则用本地 Ollama(免费、独立于云端;开发机默认走这条)
      3) LLM_FALLBACK_PROVIDER=none → 抛错,由调用方决定不挂中间件
    """
    if config.LLM_FALLBACK_PROVIDER == "none":
        raise RuntimeError("LLM_FALLBACK_PROVIDER=none:已显式关闭降级备胎")

    if config.LLM_FALLBACK_PROVIDER == "cloud":
        if not config.LLM_FALLBACK_API_KEY:
            raise RuntimeError(
                "LLM_FALLBACK_PROVIDER=cloud 但缺少 LLM_FALLBACK_API_KEY。"
                "跨厂商降级需要另一家厂商的 key(否则与主模型同源,降级无效)。"
            )
        return init_chat_model(
            model=config.LLM_FALLBACK_MODEL or config.LLM_MODEL,
            model_provider="openai",
            api_key=config.LLM_FALLBACK_API_KEY,
            base_url=config.LLM_FALLBACK_BASE_URL,
            temperature=config.LLM_TEMPERATURE,
            timeout=config.LLM_TIMEOUT,
        )

    # 默认:本地 Ollama(独立于云端,不受云端 key/余额影响)
    return get_ollama_model(config.LLM_FALLBACK_MODEL or None)


def get_ollama_model(model_name: str | None = None) -> ChatOpenAI:
    """本机 Ollama 模型(仅本地开发/降级验证用)。

    第02章 §4.4(p24-25)本地模型部署与调用。

    为什么用 qwen3:0.6b 而不是 deepseek-r1:1.5b:
        r1 系列没有 tools 模板,Agent 场景(请求必带工具 schema)
        会被 Ollama 直接 400 拒绝;qwen3:0.6b 支持工具调用。
    排查手段:第02章 §6.2(p50-53)的 profile 能力画像 —— 用
        `get_ollama_model().profile.get("tool_calling")`
        可以提前判断备胎模型是否支持工具调用。
    """
    return ChatOpenAI(
        api_key="ollama",
        base_url=config.OLLAMA_BASE_URL.rstrip("/") + "/v1",
        model=model_name or config.OLLAMA_MODEL,
        temperature=config.LLM_TEMPERATURE,
        timeout=config.LLM_TIMEOUT,
    )


if __name__ == "__main__":
    # 第02章 §6.2(p50-53):打印模型能力画像,确认 tool_calling / structured_output
    # 运行(项目根目录):.venv\\python src\\model.py
    main_model = get_chat_model()
    print(f"provider      : {config.LLM_PROVIDER}")
    print(f"model         : {config.LLM_MODEL}")
    print(f"temperature   : {config.LLM_TEMPERATURE}")
    print(f"max_tokens    : {config.LLM_MAX_TOKENS}")
    print(f"timeout       : {config.LLM_TIMEOUT}")
    print(f"max_retries   : {config.LLM_MAX_RETRIES}")
    print(f"profile       : {getattr(main_model, 'profile', None)}")
    print(f"langsmith     : tracing={config.LANGSMITH_TRACING} project={config.LANGSMITH_PROJECT}")
    print(f"embedding     : {config.EMBED_MODEL} @ {config.EMBED_BASE_URL} (dim={config.EMBED_DIM})")
    print(f"embed key     : {'已配置' if config.EMBED_API_KEY else '未配置(待补)'}")
