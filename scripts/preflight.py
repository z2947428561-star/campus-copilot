"""正式部署前的只读配置检查；不会打印密钥，也不会连接生产服务。"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
_DOMAIN = re.compile(r"^(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


def check_environment(values: dict[str, str | None], root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    for key in ("DEEPSEEK_API_KEY", "EMBED_API_KEY"):
        value = (values.get(key) or "").strip()
        if not value or "在这里" in value or "your" in value.lower():
            errors.append(f"{key} 未配置有效值")

    password = (values.get("POSTGRES_PASSWORD") or "").strip()
    if len(password) < 20 or not password.isascii() or not password.isalnum():
        errors.append("POSTGRES_PASSWORD 需至少 20 位 ASCII 字母数字（避免 URL 转义问题）")

    domain = (values.get("CAMPUS_DOMAIN") or "").strip().lower()
    if not _DOMAIN.fullmatch(domain):
        errors.append("CAMPUS_DOMAIN 需填写已准备使用的公网域名，不可用 localhost/IP")

    if (values.get("LANGSMITH_TRACING") or "false").strip().lower() != "false":
        errors.append("正式环境 LANGSMITH_TRACING 应为 false，避免学生问答默认外传")
    if (values.get("KB_BACKEND") or "milvus").strip().lower() not in {"milvus", "chroma"}:
        errors.append("KB_BACKEND 只能为 milvus 或 chroma")
    if not any((root / "data" / "raw_docs").glob("*.md")):
        errors.append("data/raw_docs 缺少可用于构建知识库的 Markdown 文档")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    args = parser.parse_args()
    if not args.env_file.is_file():
        print(f"FAIL: 环境文件不存在: {args.env_file}")
        return 1
    errors = check_environment(dotenv_values(args.env_file))
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        print(f"配置预检未通过：{len(errors)} 项；未检查 DNS、证书或外部 API 可用性。")
        return 1
    print("配置预检通过；仍需验证 DNS、HTTPS 证书、外部 API 和在线服务探活。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
