"""Deterministic model for local browser tests; never constructs an API client."""
import time

from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool

from agent.memory import get_checkpointer
from agent.middleware import get_call_limit_middlewares
from context import UserContext


class BrowserTestModel(BaseChatModel):
    @property
    def _llm_type(self):
        return "offline-browser-test"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        last = messages[-1]
        if last.type == "tool":
            rejected = "rejected" in last.content.lower() or "拒绝" in last.content
            reply = AIMessage("已取消测试操作" if rejected else "已确认测试操作")
        elif "确认" in last.content or "GPA" in last.content:
            count = 2 if "双重" in last.content else 1
            reply = AIMessage(content="", tool_calls=[{
                "name": "calculate_gpa", "args": {"semester": str(index)},
                "id": f"test-{len(messages)}-{index}", "type": "tool_call",
            } for index in range(count)])
        else:
            if "慢请求" in last.content:
                time.sleep(3)
            reply = AIMessage("中文流式测试通过：" + last.content)
        return ChatResult(generations=[ChatGeneration(message=reply)])


def build_agent(*, summarize=False):
    @tool
    def calculate_gpa(semester: str = "test") -> str:
        """Return fictional GPA data for browser tests."""
        return "测试成绩 3.7，学期 " + semester

    middleware = get_call_limit_middlewares()
    if summarize:
        from langchain.agents.middleware import SummarizationMiddleware
        from langchain_core.language_models.fake_chat_models import FakeListChatModel
        middleware.append(SummarizationMiddleware(model=FakeListChatModel(responses=['synthetic-summary']),
            trigger=('messages', 6), keep=('messages', 2)))
    middleware.append(HumanInTheLoopMiddleware(
        interrupt_on={"calculate_gpa": {"allowed_decisions": ["approve", "reject"],
                                        "description": "测试确认"}}))
    return create_agent(
        model=BrowserTestModel(), tools=[calculate_gpa],
        checkpointer=get_checkpointer(),
        context_schema=UserContext,
        middleware=middleware,
    )
