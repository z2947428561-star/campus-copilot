"""Interactively reset one existing local account without exposing passwords in arguments."""

from __future__ import annotations

import getpass
import re
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import auth  # noqa: E402


def account_exists(username: str) -> bool:
    with auth._conn() as conn:
        return conn.execute(
            f"SELECT 1 FROM web_users WHERE username = {auth._ph()}",
            (username,),
        ).fetchone() is not None


def reset_password(username: str, password: str) -> bool:
    """Update an existing account and invalidate its sessions atomically."""
    if (not auth.MIN_PASSWORD_LEN <= len(password) <= 128
            or not re.search(r"[A-Za-z]", password)
            or not re.search(r"[0-9]", password)):
        raise ValueError("新密码需为 8–128 位，且同时包含字母和数字")

    salt = secrets.token_hex(16)
    with auth._conn() as conn:
        updated = conn.execute(
            f"UPDATE web_users SET password_hash = {auth._ph()}, salt = {auth._ph()} "
            f"WHERE username = {auth._ph()}",
            (auth._hash_password(password, salt), salt, username),
        )
        if updated.rowcount != 1:
            return False
        conn.execute(
            f"DELETE FROM web_tokens WHERE username = {auth._ph()}",
            (username,),
        )
        conn.commit()
    return True


def main() -> int:
    print("仅重置本机已有账号；不会创建账号。输入的密码不会显示。")
    username = input("用户名：").strip()
    if not username or not account_exists(username):
        print("未找到该账号，未作任何更改。")
        return 1
    if input("再次输入用户名以确认：").strip() != username:
        print("两次用户名不一致，未作任何更改。")
        return 1

    password = getpass.getpass("新密码：")
    confirmation = getpass.getpass("再次输入新密码：")
    if password != confirmation:
        print("两次密码不一致，未作任何更改。")
        return 1
    try:
        updated = reset_password(username, password)
    except ValueError as exc:
        print(f"{exc}；未作任何更改。")
        return 1
    if not updated:
        print("账号已不存在，未作任何更改。")
        return 1
    print("密码已更新，旧登录会话已失效。请回到网页重新登录。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
