"""Local publication registry. Immutable collections first, transactional pointer second."""
from contextlib import closing, contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from urllib.parse import urlsplit
import uuid

import config

ROOT = Path(__file__).resolve().parents[1]


class PublicationConflict(ValueError):
    pass


def absolute_path(value):
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _endpoint(value):
    parsed = urlsplit(value)
    # Credentials and query parameters never enter the registry or status output.
    return (parsed.scheme, parsed.hostname, parsed.port, parsed.path)


def scope():
    if config.KB_BACKEND not in {"chroma", "milvus"}:
        raise ValueError("Unsupported KB_BACKEND")
    location = str(absolute_path(config.CHROMA_DIR).resolve()) if config.KB_BACKEND == "chroma" else (
        _endpoint(config.MILVUS_URI), config.MILVUS_DB_NAME)
    return _digest((config.KB_BACKEND, location, config.MILVUS_COLLECTION))


def embedding_contract():
    if config.EMBED_BACKEND == "ollama":
        model = ("ollama", config.EMBED_OLLAMA_MODEL, _endpoint(config.OLLAMA_BASE_URL))
    else:
        model = ("cloud", config.EMBED_MODEL, _endpoint(config.EMBED_BASE_URL),
                 config.EMBED_CHECK_CTX_LENGTH, config.EMBED_SEND_DIMENSIONS)
    return _digest((model, config.EMBED_DIM, "COSINE"))


@contextmanager
def _connection(*, write=False):
    path = absolute_path(config.KB_REGISTRY_PATH)
    if write:
        path.parent.mkdir(parents=True, exist_ok=True)
    uri = path.resolve().as_uri() + ("?mode=rwc" if write else "?mode=ro")
    with closing(sqlite3.connect(uri, uri=True, timeout=10)) as conn:
        conn.row_factory = sqlite3.Row
        with conn:
            if write:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute("""CREATE TABLE IF NOT EXISTS kb_heads (
                    scope TEXT PRIMARY KEY, active TEXT NOT NULL, previous TEXT,
                    revision INTEGER NOT NULL)""")
                conn.execute("""CREATE TABLE IF NOT EXISTS kb_releases (
                    scope TEXT NOT NULL, generation TEXT PRIMARY KEY, collection TEXT NOT NULL,
                    state TEXT NOT NULL, embedding TEXT NOT NULL, chunk_count INTEGER NOT NULL,
                    content_hash TEXT NOT NULL, created_at TEXT NOT NULL, base_revision INTEGER NOT NULL)""")
            else:
                conn.execute("PRAGMA query_only=ON")
            yield conn


def _release(conn, generation, target):
    if generation == "legacy":
        return {"generation": "legacy", "collection": config.MILVUS_COLLECTION,
                "state": "legacy", "embedding": "unknown"}
    row = conn.execute("SELECT * FROM kb_releases WHERE scope=? AND generation=?", (target, generation)).fetchone()
    if not row:
        raise ValueError("Index registry references a missing release")
    return dict(row)


def snapshot(*, include_releases=True):
    target = scope()
    if not absolute_path(config.KB_REGISTRY_PATH).exists():
        return {"revision": 0, "active": {"generation": "legacy", "collection": config.MILVUS_COLLECTION,
                "state": "legacy", "embedding": "unknown"}, "previous": None, "releases": []}
    with _connection() as conn:
        head = conn.execute("SELECT * FROM kb_heads WHERE scope=?", (target,)).fetchone()
        active = _release(conn, head["active"] if head else "legacy", target)
        previous = _release(conn, head["previous"], target) if head and head["previous"] else None
        releases = [dict(row) for row in conn.execute(
            "SELECT * FROM kb_releases WHERE scope=? ORDER BY created_at DESC", (target,))] if include_releases else []
    return {"revision": head["revision"] if head else 0, "active": active,
            "previous": previous, "releases": releases}


def begin(chunks):
    before = snapshot()
    generation = uuid.uuid4().hex
    # Both drivers accept this restricted physical name; no legacy collection is reused.
    prefix = "".join(c if c.isascii() and (c.isalnum() or c == "_") else "_"
                     for c in config.MILVUS_COLLECTION)[:40]
    name = "kb_" + prefix + "_v_" + generation
    record = {"scope": scope(), "generation": generation, "collection": name, "state": "building",
              "embedding": embedding_contract(), "chunk_count": len(chunks),
              "content_hash": _digest([(d.page_content, d.metadata) for d in chunks]),
              "created_at": datetime.now(timezone.utc).isoformat(), "base_revision": before["revision"]}
    with _connection(write=True) as conn:
        conn.execute("INSERT INTO kb_releases VALUES (?,?,?,?,?,?,?,?,?)", tuple(record.values()))
    return record


def mark(generation, state):
    if state not in {"ready", "failed"}:
        raise ValueError("Invalid build state")
    with _connection(write=True) as conn:
        conn.execute("UPDATE kb_releases SET state=? WHERE scope=? AND generation=? AND state='building'",
                     (state, scope(), generation))


def switch(generation, expected_revision):
    """Compare and swap under a SQLite write transaction; rollback uses the same path."""
    if not isinstance(expected_revision, int) or expected_revision < 0:
        raise ValueError("An explicit non-negative expected revision is required")
    target = scope()
    with _connection(write=True) as conn:
        head = conn.execute("SELECT * FROM kb_heads WHERE scope=?", (target,)).fetchone()
        revision = head["revision"] if head else 0
        if revision != expected_revision:
            raise PublicationConflict(f"Index changed: expected revision {expected_revision}, current {revision}")
        release = _release(conn, generation, target)
        if generation != "legacy" and (release["state"] != "ready" or release["embedding"] != embedding_contract()):
            raise ValueError("Release is not ready or embedding configuration differs")
        active = head["active"] if head else "legacy"
        if active == generation:
            raise PublicationConflict("Release is already active")
        conn.execute("""INSERT INTO kb_heads VALUES (?,?,?,?) ON CONFLICT(scope) DO UPDATE SET
                     active=excluded.active, previous=excluded.previous, revision=excluded.revision""",
                     (target, generation, active, revision + 1))
    return snapshot()
