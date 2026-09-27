"""Web 鉴权:注册 / 登录 / Bearer token 校验。

为什么必须存在(docs/milestones.md M6 部署前置清单第 7 条):
    旧版 /api/chat 的 user_id 直接来自请求体 —— 任何人把它改成 "alice"
    就能读到 alice 的画像与会话历史,是典型的水平越权(IDOR)。
    现在 user_id 只能从有效 token 解析,请求体不再携带 user_id。

设计取舍(面试可答):
- 密码:hashlib.pbkdf2_hmac(sha256, 12 万次迭代)+ 每用户 16 字节随机盐。
  选 stdlib 而非 bcrypt/argon2 是刻意的 —— 部署镜像不引入新依赖;
  pbkdf2 是 NIST 认可的 KDF,12 万次迭代对本量级应用足够。
- token:secrets.token_urlsafe(32),**服务端只存 SHA-256 哈希** ——
  数据库泄漏时攻击者拿到的是哈希,不能直接冒用 token(与密码同理)。
- 过期:30 天,过期即 401;没有滑动续期(同学一学期内重登一次可接受,
  换取实现与审计的简单)。
- 存储跟随 MEMORY_BACKEND:postgres 主路径(与记忆同库),
  sqlite 兜底(本地无 PG 时也能跑 Web)。
- user_id 即用户名:直接复用记忆层的 namespace / thread_id 语义,
  不引入第二层 id 映射。
"""
from __future__ import annotations

import hashlib
import logging
import re
import secrets
import sqlite3
import time
import threading
from collections import OrderedDict, deque
from contextlib import contextmanager

import config

logger = logging.getLogger("campus")

# 新账号:专业缩写(3 个大写字母)+入学年月(YYMM)+3 位数字。
# 只限制新注册；已有账号仍可登录，避免把本地旧数据锁在账号外。
_USERNAME_RE = re.compile(r"[A-Z]{3}[0-9]{2}(?:0[1-9]|1[0-2])[0-9]{3}\Z")
MIN_PASSWORD_LEN = 8

_PBKDF2_ROUNDS = 120_000
TOKEN_TTL_SECONDS = 30 * 24 * 3600  # 30 天


class AuthError(Exception):
    """鉴权失败(用户名占用 / 凭证错误 / token 无效),message 可直接给前端。"""


class AuthRateLimit(AuthError):
    """同一用户名短时间内登录尝试过多。"""


_login_lock = threading.Lock()
_login_attempts: OrderedDict[str, deque[float]] = OrderedDict()
_MAX_TRACKED_NAMES = 10_000


def _check_login_rate(username: str) -> None:
    """按用户名限速；单进程有效，公网多副本仍需网关/共享存储限流。"""
    now = time.monotonic()
    with _login_lock:
        attempts = _login_attempts.setdefault(username, deque())
        _login_attempts.move_to_end(username)
        while attempts and now - attempts[0] >= config.LOGIN_FAILURE_WINDOW_SECONDS:
            attempts.popleft()
        if len(attempts) >= config.LOGIN_FAILURE_LIMIT:
            raise AuthRateLimit("登录尝试过于频繁，请稍后再试")
        # 先记账，避免并发请求同时通过检查；成功登录后再清除。
        attempts.append(now)
        while len(_login_attempts) > _MAX_TRACKED_NAMES:
            _login_attempts.popitem(last=False)


def _use_pg() -> bool:
    return (config.MEMORY_BACKEND or "").lower() == "postgres"


@contextmanager
def _conn():
    """按后端开连接;占位符差异由 _ph() 吸收。"""
    if _use_pg():
        import psycopg

        with psycopg.connect(config.DATABASE_URL) as c:
            yield c
    else:
        from agent.memory import DB_PATH

        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(str(DB_PATH))
        try:
            with c:
                yield c
        finally:
            c.close()


def _ph() -> str:
    return "%s" if _use_pg() else "?"


def init_auth() -> None:
    """建表(幂等),由 server lifespan 在启动时调用。"""
    bigserial = "BIGSERIAL" if _use_pg() else "INTEGER"
    with _conn() as c:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS web_users (
                id            {bigserial} PRIMARY KEY {pg_autoinc},
                username      TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                salt          TEXT NOT NULL,
                created_at    DOUBLE PRECISION NOT NULL
            )
            """.format(bigserial=bigserial, pg_autoinc="AUTOINCREMENT" if not _use_pg() else "")
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS web_tokens (
                token_hash TEXT PRIMARY KEY,
                username   TEXT NOT NULL,
                created_at DOUBLE PRECISION NOT NULL,
                expires_at DOUBLE PRECISION NOT NULL
            )
            """
        )
        c.commit()
    logger.info("[鉴权] 表就绪 backend=%s", "postgres" if _use_pg() else "sqlite")


def _hash_password(password: str, salt_hex: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), _PBKDF2_ROUNDS
    ).hex()


def _hash_token(token: str) -> str:
    """token 只在服务端存哈希,明文只出现在响应里一次。"""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _issue_token(username: str) -> str:
    token = secrets.token_urlsafe(32)
    now = time.time()
    with _conn() as c:
        c.execute(
            f"INSERT INTO web_tokens (token_hash, username, created_at, expires_at) "
            f"VALUES ({_ph()}, {_ph()}, {_ph()}, {_ph()})",
            (_hash_token(token), username, now, now + TOKEN_TTL_SECONDS),
        )
        c.commit()
    return token


def register(username: str, password: str) -> str:
    """注册并直接签发 token(免二次登录)。"""
    username = (username or "").strip()
    if not _USERNAME_RE.fullmatch(username):
        raise AuthError("用户名需为 3 位大写字母 + 7 位数字")
    if (len(password or "") < MIN_PASSWORD_LEN
            or not re.search(r"[A-Za-z]", password)
            or not re.search(r"[0-9]", password)):
        raise AuthError(f"密码至少 {MIN_PASSWORD_LEN} 位，且同时包含字母和数字")

    salt = secrets.token_hex(16)
    try:
        with _conn() as c:
            c.execute(
                f"INSERT INTO web_users (username, password_hash, salt, created_at) "
                f"VALUES ({_ph()}, {_ph()}, {_ph()}, {_ph()})",
                (username, _hash_password(password, salt), salt, time.time()),
            )
            c.commit()
    except Exception as e:  # 唯一约束冲突(sqlite3.IntegrityError / psycopg.errors.UniqueViolation)
        if "unique" in str(e).lower() or "UNIQUE" in type(e).__name__ or "UniqueViolation" in type(e).__name__:
            raise AuthError("用户名已被注册") from e
        raise
    logger.info("[鉴权] 新用户注册: %s", username)
    return _issue_token(username)


def login(username: str, password: str) -> str:
    username = (username or "").strip()
    _check_login_rate(username)
    with _conn() as c:
        row = c.execute(
            f"SELECT password_hash, salt FROM web_users WHERE username = {_ph()}",
            (username,),
        ).fetchone()
    # 用户不存在与密码错误返回同一句话,不暴露"哪个注册过"
    if row is None or not secrets.compare_digest(row[0], _hash_password(password or "", row[1])):
        raise AuthError("用户名或密码错误")
    with _login_lock:
        _login_attempts.pop(username, None)
    return _issue_token(username)


def authenticate(token: str) -> str | None:
    """token → username;无效或过期返回 None。"""
    if not token:
        return None
    with _conn() as c:
        row = c.execute(
            f"SELECT username, expires_at FROM web_tokens WHERE token_hash = {_ph()}",
            (_hash_token(token),),
        ).fetchone()
    if row is None:
        return None
    if row[1] < time.time():
        revoke(token)
        return None
    return row[0]


def revoke(token: str) -> None:
    """登出:删除该 token(幂等)。"""
    if not token:
        return
    with _conn() as c:
        c.execute(
            f"DELETE FROM web_tokens WHERE token_hash = {_ph()}",
            (_hash_token(token),),
        )
        c.commit()
