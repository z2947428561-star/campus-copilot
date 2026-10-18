"""Project checkpoint state into the public Web conversation contract."""
from agent.streaming import InterruptInfo, extract_text
import config


def conversation_state(agent, cfg, *, snapshot=None):
    snapshot = agent.get_state(cfg) if snapshot is None else snapshot
    values = snapshot.values or {}
    messages = []
    for message in values.get("messages", []):
        kind = getattr(message, "type", None)
        if kind not in ("human", "ai"):
            continue
        if getattr(message, 'additional_kwargs', {}).get('lc_source') == 'summarization':
            continue
        text = extract_text(message)
        if text:
            messages.append({"role": "user" if kind == "human" else "assistant", "text": text})
    pending = []
    for interrupt in snapshot.interrupts:
        info = InterruptInfo.from_interrupt(interrupt)
        for index, action in enumerate(info.action_requests):
            pending.append({
                "tool": action.get("name"), "args": action.get("args", {}),
                "description": action.get("description", ""),
                "allowed_decisions": info.allowed_decisions(index),
            })
    model_calls = values.get("thread_model_call_count", 0)
    tool_calls = values.get("thread_tool_call_count", {}).get("__all__", 0)
    return {
        "messages": messages, "pending": pending,
        "checkpoint_id": (snapshot.config or {}).get("configurable", {}).get("checkpoint_id"),
        "exhausted": (model_calls >= config.MODEL_CALL_THREAD_LIMIT
                      or tool_calls >= config.TOOL_CALL_THREAD_LIMIT),
        "usage": {"model_calls": model_calls, "tool_calls": tool_calls,
                  "model_limit": config.MODEL_CALL_THREAD_LIMIT,
                  "tool_limit": config.TOOL_CALL_THREAD_LIMIT},
    }
