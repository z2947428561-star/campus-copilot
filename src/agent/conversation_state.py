"""Project checkpoint state into the public Web conversation contract."""
from agent.streaming import InterruptInfo, extract_text


def conversation_state(agent, cfg):
    snapshot = agent.get_state(cfg)
    values = snapshot.values or {}
    messages = []
    for message in values.get("messages", []):
        kind = getattr(message, "type", None)
        if kind not in ("human", "ai"):
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
    return {
        "messages": messages, "pending": pending,
        "checkpoint_id": (snapshot.config or {}).get("configurable", {}).get("checkpoint_id"),
    }
