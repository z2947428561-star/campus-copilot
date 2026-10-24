"""Durable user-visible messages, independent of the agent's reduced context."""
import hashlib
import time
from contextlib import closing

from agent.streaming import extract_text
from storage import personal_connection, placeholder, uses_postgres


def init_history():
    sequence = 'BIGSERIAL PRIMARY KEY' if uses_postgres() else 'INTEGER PRIMARY KEY AUTOINCREMENT'
    with personal_connection() as conn:
        conn.execute(f"""CREATE TABLE IF NOT EXISTS web_chat_messages (
            sequence {sequence}, user_id TEXT NOT NULL, thread_id TEXT NOT NULL,
            message_id TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('user','assistant')),
            text TEXT NOT NULL, semester_id TEXT, recorded_at DOUBLE PRECISION NOT NULL,
            UNIQUE(user_id,thread_id,message_id))""")
        conn.execute("""CREATE INDEX IF NOT EXISTS idx_web_chat_messages_thread
            ON web_chat_messages(user_id,thread_id,sequence)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS web_chat_imports (
            user_id TEXT NOT NULL, thread_id TEXT NOT NULL, imported_at DOUBLE PRECISION NOT NULL,
            PRIMARY KEY(user_id,thread_id))""")


def _visible(message):
    kind = getattr(message, 'type', None)
    if kind not in {'human', 'ai'}:
        return False
    # Framework summaries are context instructions, never a user's own words.
    return getattr(message, 'additional_kwargs', {}).get('lc_source') != 'summarization'


def _rows(messages, semester_id, *, hide_tool_narration=False, question=None):
    rows = []
    for index, message in enumerate(messages):
        if not _visible(message):
            continue
        if hide_tool_narration and getattr(message, 'type', None) == 'ai' and getattr(message, 'tool_calls', None):
            continue
        text = extract_text(message)
        if message.type == 'human':
            question = text
        if hide_tool_narration and message.type == 'ai':
            from dorm_answer import format_answer
            text = format_answer(text, question)
        if not text:
            continue
        role = 'user' if message.type == 'human' else 'assistant'
        # Real graph messages have stable IDs. Older custom checkpoints may not.
        key = getattr(message, 'id', None) or 'legacy:' + hashlib.sha256(
            f'{index}:{role}:{text}'.encode()).hexdigest()
        rows.append((key, role, text, semester_id, time.time()))
    return rows


def _insert(conn, user_id, thread_id, rows):
    ph = placeholder()
    if rows:
        with closing(conn.cursor()) as cursor:
            cursor.executemany(
                'INSERT INTO web_chat_messages(user_id,thread_id,message_id,role,text,semester_id,recorded_at) '
                f'VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph}) '
                'ON CONFLICT(user_id,thread_id,message_id) DO NOTHING',
                [(user_id, thread_id, *row) for row in rows])


def capture(user_id, thread_id, messages, semester_id=None, *, question=None):
    rows = _rows(messages, semester_id, hide_tool_narration=user_id.startswith('xmumdorm:'), question=question)
    if rows:
        with personal_connection() as conn:
            _insert(conn, user_id, thread_id, rows)


def import_checkpoints(user_id, thread_id, agent, cfg, snapshot):
    """Backfill once, oldest first. Existing checkpoints may retain pre-summary text."""
    ph = placeholder()
    with personal_connection(read_only=True) as conn:
        if conn.execute(f'SELECT 1 FROM web_chat_imports WHERE user_id={ph} AND thread_id={ph}',
                        (user_id, thread_id)).fetchone():
            return
    read_history = getattr(agent, 'get_state_history', None)
    snapshots = list(read_history(cfg)) if callable(read_history) else []
    if not snapshots:
        snapshots = [snapshot]
    rows, seen = [], set()
    for state in reversed(snapshots):
        for row in _rows((state.values or {}).get('messages', []), None, hide_tool_narration=user_id.startswith('xmumdorm:')):
            if row[0] not in seen:
                seen.add(row[0])
                rows.append(row)
    # Import and its marker commit together; repeated refreshes are idempotent.
    with personal_connection() as conn:
        _insert(conn, user_id, thread_id, rows)
        conn.execute('INSERT INTO web_chat_imports(user_id,thread_id,imported_at) '
                     f'VALUES ({ph},{ph},{ph}) ON CONFLICT(user_id,thread_id) DO NOTHING',
                     (user_id, thread_id, time.time()))


def messages(user_id, thread_id):
    ph = placeholder()
    with personal_connection(read_only=True) as conn:
        rows = conn.execute('SELECT role,text FROM web_chat_messages '
                            f'WHERE user_id={ph} AND thread_id={ph} ORDER BY sequence', (user_id, thread_id)).fetchall()
    return [{'role': role, 'text': text} for role, text in rows]


def position(user_id, thread_id):
    ph = placeholder()
    with personal_connection(read_only=True) as conn:
        return conn.execute('SELECT COALESCE(MAX(sequence),0) FROM web_chat_messages '
                            f'WHERE user_id={ph} AND thread_id={ph}', (user_id, thread_id)).fetchone()[0]


def unrecorded_reply(user_id, thread_id, after, streamed_text, message_id, semester_id):
    """Keep streamed text when a custom graph/failure has no completed message update."""
    if not streamed_text:
        return
    ph = placeholder()
    with personal_connection() as conn:
        rows = conn.execute('SELECT text FROM web_chat_messages '
                            f'WHERE user_id={ph} AND thread_id={ph} AND sequence>{ph} '
                            "AND role='assistant' ORDER BY sequence", (user_id, thread_id, after)).fetchall()
        written = ''.join(row[0] for row in rows)
        if streamed_text.startswith(written):
            remaining = streamed_text[len(written):]
            if remaining:
                _insert(conn, user_id, thread_id, [(message_id, 'assistant', remaining, semester_id, time.time())])
