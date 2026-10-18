"""Local publication registry. Immutable collections first, transactional pointer second."""
from contextlib import closing, contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
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
    if config.KB_BACKEND == "chroma":
        vectors = absolute_path(config.CHROMA_DIR).resolve()
        registry = absolute_path(config.KB_REGISTRY_PATH).resolve()
        try:
            location = ("registry-relative-v1", os.path.normcase(os.path.relpath(vectors, registry.parent)).replace("\\", "/"))
        except ValueError:  # Windows paths on different drives cannot be relative.
            location = ("absolute-v1", os.path.normcase(str(vectors)))
    else:
        location = (_endpoint(config.MILVUS_URI), config.MILVUS_DB_NAME)
    return _digest((config.KB_BACKEND, location, config.MILVUS_COLLECTION))


def _legacy_chroma_scope(directory):
    return _digest(("chroma", str(absolute_path(directory).resolve()), config.MILVUS_COLLECTION))


def _absolute_chroma_scope(directory):
    return _digest(("chroma", ("absolute-v1", os.path.normcase(str(absolute_path(directory).resolve()))),
                    config.MILVUS_COLLECTION))


def content_hash(chunks):
    return _digest([(d.page_content, d.metadata) for d in chunks])


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
                conn.execute("BEGIN")
            yield conn


def _release(conn, generation, target):
    if generation == "legacy":
        return {"generation": "legacy", "collection": config.MILVUS_COLLECTION,
                "state": "legacy", "embedding": "unknown"}
    row = conn.execute("SELECT * FROM kb_releases WHERE scope=? AND generation=?", (target, generation)).fetchone()
    if not row:
        raise ValueError("Index registry references a missing release")
    return dict(row)


def _has_scope(conn, target):
    return conn.execute("""SELECT 1 FROM kb_heads WHERE scope=? UNION ALL
                        SELECT 1 FROM kb_releases WHERE scope=? LIMIT 1""", (target, target)).fetchone() is not None


def _move_scope(conn, source, target):
    conn.execute("UPDATE kb_heads SET scope=? WHERE scope=?", (target, source))
    conn.execute("UPDATE kb_releases SET scope=? WHERE scope=?", (target, source))


def _registry_scope(conn, *, migrate=False):
    target = scope()
    if config.KB_BACKEND == "chroma":
        legacy = _legacy_chroma_scope(config.CHROMA_DIR)
        if _has_scope(conn, legacy):
            if _has_scope(conn, target):
                raise ValueError("Both legacy and portable index scopes exist; refuse to merge")
            if migrate:
                _move_scope(conn, legacy, target)
            else:
                return legacy
    return target


def _snapshot(conn, target, *, include_releases=True):
    head = conn.execute("SELECT * FROM kb_heads WHERE scope=?", (target,)).fetchone()
    active = _release(conn, head["active"] if head else "legacy", target)
    previous = _release(conn, head["previous"], target) if head and head["previous"] else None
    releases = [dict(row) for row in conn.execute(
        "SELECT * FROM kb_releases WHERE scope=? ORDER BY created_at DESC", (target,))] if include_releases else []
    return {"revision": head["revision"] if head else 0, "active": active,
            "previous": previous, "releases": releases}


def snapshot(*, include_releases=True):
    scope()  # Validate the backend even when no registry exists.
    if not absolute_path(config.KB_REGISTRY_PATH).exists():
        return {"revision": 0, "active": {"generation": "legacy", "collection": config.MILVUS_COLLECTION,
                "state": "legacy", "embedding": "unknown"}, "previous": None, "releases": []}
    with _connection() as conn:
        return _snapshot(conn, _registry_scope(conn), include_releases=include_releases)


def rebind_chroma(old_directory, expected_revision, validate):
    """Validate a restored old-path scope, then move its records in one transaction."""
    if config.KB_BACKEND != "chroma" or not Path(old_directory).is_absolute():
        raise ValueError("Rebinding requires Chroma and its old absolute directory")
    if not isinstance(expected_revision, int) or expected_revision < 0:
        raise ValueError("An explicit non-negative expected revision is required")
    if not absolute_path(config.KB_REGISTRY_PATH).is_file():
        raise ValueError("Restore the publication registry before rebinding")
    target = scope()
    with _connection(write=True) as conn:
        sources = [source for source in (_legacy_chroma_scope(old_directory), _absolute_chroma_scope(old_directory))
                   if _has_scope(conn, source)]
        if len(sources) != 1:
            raise ValueError("Missing or ambiguous publication records for the old Chroma directory")
        source = sources[0]
        if _has_scope(conn, target) or (source != _legacy_chroma_scope(config.CHROMA_DIR)
                                      and _has_scope(conn, _legacy_chroma_scope(config.CHROMA_DIR))):
            raise PublicationConflict("The target already has publication records")
        state = _snapshot(conn, source)
        if state["revision"] != expected_revision:
            raise PublicationConflict(f"Index changed: expected revision {expected_revision}, current {state['revision']}")
        validate(state)
        _move_scope(conn, source, target)
    return snapshot()


def begin(chunks):
    before = snapshot()
    generation = uuid.uuid4().hex
    # Both drivers accept this restricted physical name; no legacy collection is reused.
    prefix = "".join(c if c.isascii() and (c.isalnum() or c == "_") else "_"
                     for c in config.MILVUS_COLLECTION)[:40]
    name = "kb_" + prefix + "_v_" + generation
    record = {"scope": scope(), "generation": generation, "collection": name, "state": "building",
              "embedding": embedding_contract(), "chunk_count": len(chunks),
              "content_hash": content_hash(chunks),
              "created_at": datetime.now(timezone.utc).isoformat(), "base_revision": before["revision"]}
    with _connection(write=True) as conn:
        record["scope"] = _registry_scope(conn, migrate=True)
        conn.execute("INSERT INTO kb_releases VALUES (?,?,?,?,?,?,?,?,?)", tuple(record.values()))
    return record


def mark(generation, state):
    if state not in {"ready", "failed"}:
        raise ValueError("Invalid build state")
    with _connection(write=True) as conn:
        target = _registry_scope(conn, migrate=True)
        conn.execute("UPDATE kb_releases SET state=? WHERE scope=? AND generation=? AND state='building'",
                     (state, target, generation))


def switch(generation, expected_revision):
    """Compare and swap under a SQLite write transaction; rollback uses the same path."""
    if not isinstance(expected_revision, int) or expected_revision < 0:
        raise ValueError("An explicit non-negative expected revision is required")
    with _connection(write=True) as conn:
        target = _registry_scope(conn, migrate=True)
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
