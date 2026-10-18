"""Owned Web conversations; checkpoint state remains in LangGraph."""
import time
from uuid import uuid4

from storage import personal_connection as _conn, placeholder as _ph
from agent.runtime import default_thread_id


def init_conversations():
    with _conn() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS web_conversations (
            user_id TEXT NOT NULL, conversation_id TEXT NOT NULL,
            title TEXT NOT NULL, created_at DOUBLE PRECISION NOT NULL,
            PRIMARY KEY (user_id, conversation_id))""")
        conn.execute("""CREATE TABLE IF NOT EXISTS web_conversation_semesters (
            user_id TEXT NOT NULL, conversation_id TEXT NOT NULL, semester_id TEXT NOT NULL,
            PRIMARY KEY (user_id, conversation_id))""")
        conn.commit()


def semester_for(user_id, conversation_id):
    with _conn() as conn:
        row = conn.execute(
            f"SELECT semester_id FROM web_conversation_semesters WHERE user_id={_ph()} AND conversation_id={_ph()}",
            (user_id, conversation_id)).fetchone()
    return row[0] if row else None


def set_semester(user_id, conversation_id, semester_id):
    ph = _ph()
    with _conn() as conn:
        conn.execute(
            f"INSERT INTO web_conversation_semesters(user_id,conversation_id,semester_id) VALUES ({ph},{ph},{ph}) "
            "ON CONFLICT(user_id,conversation_id) DO UPDATE SET semester_id=excluded.semester_id",
            (user_id, conversation_id, semester_id))
        conn.commit()


def _ensure_legacy(user_id):
    ph = _ph()
    with _conn() as conn:
        conn.execute(
            f"INSERT INTO web_conversations (user_id,conversation_id,title,created_at) "
            f"VALUES ({ph},{ph},{ph},{ph}) ON CONFLICT (user_id,conversation_id) DO NOTHING",
            (user_id, "main", "原有会话", 0),
        )
        conn.commit()


def list_conversations(user_id):
    _ensure_legacy(user_id)
    with _conn() as conn:
        rows = conn.execute(
            f"SELECT conversation_id,title,created_at FROM web_conversations "
            f"WHERE user_id={_ph()} ORDER BY created_at DESC, conversation_id",
            (user_id,),
        ).fetchall()
    return [dict(zip(("id", "title", "created_at"), row)) for row in rows]


def create_conversation(user_id):
    item = {"id": uuid4().hex, "title": "新会话", "created_at": time.time()}
    ph = _ph()
    with _conn() as conn:
        conn.execute(
            f"INSERT INTO web_conversations (user_id,conversation_id,title,created_at) "
            f"VALUES ({ph},{ph},{ph},{ph})",
            (user_id, item["id"], item["title"], item["created_at"]),
        )
        conn.commit()
    return item


def get_conversation(user_id, conversation_id):
    if conversation_id == "main":
        _ensure_legacy(user_id)
    ph = _ph()
    with _conn() as conn:
        row = conn.execute(
            f"SELECT conversation_id,title,created_at FROM web_conversations "
            f"WHERE user_id={ph} AND conversation_id={ph}",
            (user_id, conversation_id),
        ).fetchone()
    if row is None:
        raise KeyError(conversation_id)
    return dict(zip(("id", "title", "created_at"), row))


def thread_id_for(user_id, conversation_id):
    # Only call after ownership validation. Preserve existing main checkpoints.
    if conversation_id == "main":
        return default_thread_id(user_id)
    return f"web:{user_id}:{conversation_id}"


def name_conversation(user_id, conversation_id, message):
    ph = _ph()
    with _conn() as conn:
        conn.execute(
            f"UPDATE web_conversations SET title={ph} "
            f"WHERE user_id={ph} AND conversation_id={ph} AND title={ph}",
            (message.strip()[:40], user_id, conversation_id, "新会话"),
        )
        conn.commit()
