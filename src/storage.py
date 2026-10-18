"""Personal SQL transactions shared by auth, student records and conversations."""
from contextlib import closing, contextmanager
from pathlib import Path
import sqlite3

import config

ROOT = Path(__file__).resolve().parents[1]


def personal_path():
    path = Path(config.MEMORY_DB_PATH) if config.MEMORY_DB_PATH else ROOT / "data" / "memory.db"
    return path if path.is_absolute() else ROOT / path


def uses_postgres():
    backend = (config.MEMORY_BACKEND or "sqlite").lower()
    if backend not in {"postgres", "sqlite"}:
        raise ValueError("Unsupported MEMORY_BACKEND")
    return backend == "postgres"


def placeholder():
    return "%s" if uses_postgres() else "?"


@contextmanager
def personal_connection(*, read_only=False):
    """Own the connection and transaction. Exceptional exits roll back and close."""
    if uses_postgres():
        import psycopg
        with psycopg.connect(config.DATABASE_URL) as conn:
            if read_only:
                conn.execute("SET TRANSACTION READ ONLY")
            yield conn
        return
    path = personal_path()
    if read_only:
        target = path.resolve().as_uri() + "?mode=ro"
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        target = str(path)
    with closing(sqlite3.connect(target, uri=read_only, timeout=10)) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        if read_only:
            conn.execute("PRAGMA query_only=ON")
        with conn:
            yield conn
