"""Migrate a public catalog without resetting it, or import one versioned semester."""
import argparse
import json
from pathlib import Path
import sys
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from semesters import catalog_path, import_semester, migrate_catalog


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, help="公共校园 SQLite 文件；默认使用本机校园库")
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument("--migrate", action="store_true", help="只迁移旧结构并保留全部记录")
    operation.add_argument("--file", type=Path, help="单个学期的完整 JSON 数据文件")
    parser.add_argument("--expected-version", type=int, help="更新已有学期时须明确当前版本")
    args = parser.parse_args()
    try:
        target = args.database or catalog_path()
        if args.migrate:
            result = migrate_catalog(target)
        else:
            result = import_semester(json.loads(args.file.read_text(encoding="utf-8")), target,
                                     expected_version=args.expected_version)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (ValueError, OSError, sqlite3.Error) as exc:
        print("学期导入失败：" + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
