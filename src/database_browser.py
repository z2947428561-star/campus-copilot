"""Authenticated, read-only projections of the application's data stores.

SQL identifiers come exclusively from SPECS. Personal predicates are always supplied
by the server. Index inspection deliberately bypasses kb.get_vectorstore(): that path
creates collections and embeddings, neither of which belongs in a data browser.
"""
from contextlib import contextmanager, closing
from dataclasses import dataclass
import json
import logging
from pathlib import Path
import re
import sqlite3

import auth
import config
import student_data
import semesters

logger = logging.getLogger("campus")
DOCS_DIR = Path(__file__).resolve().parents[1] / "data/raw_docs"


class MissingTable(ValueError):
    pass


class StoreUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class Table:
    label: str
    fields: tuple
    description: str
    primary: tuple = ()


# (name, label, storage type). Auth tables and arbitrary SQL are intentionally absent.
SPECS = {
    "campus": {
        "semesters": Table("学期与版本", (("semester_id", "学期 ID", "TEXT"), ("label", "学期名称", "TEXT"),
            ("academic_year", "学年", "TEXT"), ("start_date", "开始日期", "TEXT"), ("end_date", "结束日期", "TEXT"),
            ("version", "资料版本", "INTEGER"), ("schedule_status", "排课覆盖", "TEXT"), ("is_demo", "演示配置", "BOOLEAN")),
            "已录入的学期与校历、排课资料版本；旧结构以兼容视图呈现。", ("semester_id",)),
        "courses": Table("课程目录", (("course_id", "课程代码", "TEXT"), ("name", "课程名称", "TEXT"),
            ("credits", "学分", "REAL"), ("dept", "院系", "TEXT"), ("prerequisites", "先修课程", "TEXT"),
            ("sem", "建议开课月份", "TEXT"), ("year", "年级", "INTEGER")), "公共课程目录，包含演示配置；开课月份不代表具体学期已排课。", ("course_id",)),
        "classrooms": Table("教室", (("room_id", "教室编号", "TEXT"), ("building", "教学楼", "TEXT"),
            ("type", "教室类型", "TEXT"), ("capacity", "容量", "INTEGER"),
            ("has_projector", "投影设备", "INTEGER"), ("has_ac", "空调", "INTEGER")), "演示教室及设施。", ("room_id",)),
        "timetable": Table("排课", (("id", "编号", "INTEGER"), ("room", "教室", "TEXT"),
            ("weekday", "星期", "INTEGER"), ("period", "时段", "TEXT"), ("course_id", "课程代码", "TEXT"),
            ("weeks", "教学周", "TEXT"), ("semester_id", "学期 ID", "TEXT")), "已录入的学期排课，包含演示数据。", ("id",)),
        "calendar_weeks": Table("教学周", (("week_no", "周次", "INTEGER"), ("semester", "学期", "TEXT"),
            ("academic_year", "学年", "TEXT"), ("start", "开始日期", "TEXT"), ("end", "结束日期", "TEXT"),
            ("type", "周类型", "TEXT"), ("semester_id", "学期 ID", "TEXT")), "当前录入的校历范围。", ("semester_id", "week_no")),
        "semester_events": Table("学期事件", (("id", "编号", "INTEGER"), ("name", "事件名称", "TEXT"),
            ("event_type", "事件类型", "TEXT"), ("start_date", "开始日期", "TEXT"),
            ("end_date", "结束日期", "TEXT"), ("semester_id", "学期 ID", "TEXT")), "校历中的注册、假期与考试等事件。", ("id",)),
    },
    "personal": {
        "student_grades": Table("我的成绩", (("semester", "学期", "TEXT"), ("course_id", "课程代码", "TEXT"),
            ("grade_point", "绩点", "DOUBLE PRECISION"), ("letter", "等级", "TEXT"),
            ("credits_snapshot", "录入时学分", "DOUBLE PRECISION"), ("name_snapshot", "录入时课程名称", "TEXT")),
            "仅显示当前账号在各学期自行录入的成绩。", ("semester", "course_id")),
        "student_courses": Table("我的选课", (("semester", "学期", "TEXT"), ("course_id", "课程代码", "TEXT")),
            "仅显示当前账号在各学期的选课记录。", ("semester", "course_id")),
        "web_conversations": Table("我的会话", (("conversation_id", "会话 ID", "TEXT"), ("title", "标题", "TEXT"),
            ("created_at", "创建时间戳", "DOUBLE PRECISION")), "当前账号的会话登记，不含聊天正文。", ("conversation_id",)),
    },
    "documents": {
        "snapshots": Table("政策快照", (("filename", "文件名", "TEXT"), ("title", "文档标题", "TEXT"),
            ("doc_type", "分类", "TEXT"), ("source_type", "整理方式", "TEXT"),
            ("collected_at", "采集日期", "TEXT"), ("effective_date", "生效日期", "TEXT"),
            ("source", "参考来源", "TEXT"), ("text", "快照正文", "TEXT")),
            "当前公开文件；文件存在不代表已写入向量索引。", ("filename",)),
    },
    "index": {
        "chunks": Table("已入库分块", (("id", "记录 ID", "ID"), ("title", "文档标题", "TEXT"),
            ("filename", "文件名", "TEXT"), ("doc_type", "分类", "TEXT"), ("source_type", "整理方式", "TEXT"),
            ("source", "参考来源", "TEXT"), ("collected_at", "采集日期", "TEXT"),
            ("effective_date", "生效日期", "TEXT"), ("text", "分块正文", "TEXT")),
            "按需读取实际向量集合；缺失字段显示为空。不会调用 Embedding。", ("id",)),
    },
}

SOURCES = (
    ("campus", "公共校园库", "SQLite", "公共数据"),
    ("personal", "我的数据", "PostgreSQL" if auth._use_pg() else "SQLite", "当前账号"),
    ("documents", "政策文档", "Markdown", "公开快照"),
    ("index", "向量索引", config.KB_BACKEND, "按需连接"),
)

RELATIONS = [
    {"from": "campus.timetable", "field": "semester_id", "to": "campus.semesters", "target": "semester_id", "kind": "学期关联"},
    {"from": "campus.calendar_weeks", "field": "semester_id", "to": "campus.semesters", "target": "semester_id", "kind": "学期关联"},
    {"from": "campus.semester_events", "field": "semester_id", "to": "campus.semesters", "target": "semester_id", "kind": "学期关联"},
    {"from": "campus.timetable", "field": "course_id", "to": "campus.courses", "target": "course_id", "kind": "外键"},
    {"from": "campus.timetable", "field": "room", "to": "campus.classrooms", "target": "room_id", "kind": "外键"},
    {"from": "personal.student_grades", "field": "course_id", "to": "campus.courses", "target": "course_id", "kind": "逻辑关联"},
    {"from": "personal.student_courses", "field": "course_id", "to": "campus.courses", "target": "course_id", "kind": "逻辑关联"},
    {"from": "index.chunks", "field": "filename", "to": "documents.snapshots", "target": "filename", "kind": "来源关联"},
]


def columns(spec):
    return [{"name": n, "label": label, "type": kind, "primary": n in spec.primary}
            for n, label, kind in spec.fields]


@contextmanager
def sql_connection(source):
    if source == "campus":
        # mode=ro prevents even an empty file being created for a wrong path.
        uri = student_data.CATALOG_DB.resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=2)) as conn:
            conn.execute("PRAGMA query_only=ON")
            yield conn
    else:
        with auth._conn() as conn:
            conn.execute("SET TRANSACTION READ ONLY" if auth._use_pg() else "PRAGMA query_only=ON")
            yield conn


def sql_page(source, name, spec, user_id, q, offset, size, sort, direction):
    names = [f[0] for f in spec.fields]
    ph = "?" if source == "campus" else auth._ph()
    clauses, params = [], []
    if source == "personal":
        clauses.append(f'"user_id"={ph}')
        params.append(user_id)
    if q:
        pattern = "%" + q.replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"
        clauses.append("(" + " OR ".join(f'LOWER(CAST("{n}" AS TEXT)) LIKE LOWER({ph}) ESCAPE \'!\'' for n in names) + ")")
        params.extend([pattern] * len(names))
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    ordering = [sort or spec.primary[0]] + [n for n in spec.primary if n != (sort or spec.primary[0])]
    order = ",".join(f'"{n}" {direction.upper()}' for n in ordering)
    with sql_connection(source) as conn:
        table = f'"{name}"'
        prefix = []
        if source == "campus" and "semester_id" in names and not semesters.has_column(conn, name, "semester_id"):
            terms = semesters.list_semesters()
            if len(terms) > 1:
                raise StoreUnavailable("旧结构无法确认每条记录的学期，请先迁移校历。")
            table = f'(SELECT *, ? AS semester_id FROM "{name}")'
            prefix = [terms[0]["semester_id"] if terms else ""]
        count = conn.execute(f'SELECT COUNT(*) FROM {table}{where}', [*prefix, *params]).fetchone()[0]
        fields = ",".join(f'"{n}"' for n in names)
        rows = conn.execute(f'SELECT {fields} FROM {table}{where} ORDER BY {order} LIMIT {ph} OFFSET {ph}',
                            (*prefix, *params, size, offset)).fetchall()
    return [dict(zip(names, row)) for row in rows], count


def snapshot_rows():
    rows = []
    for path in sorted(DOCS_DIR.glob("*.md")):
        raw = path.read_text(encoding="utf-8")
        match = re.match(r"\A---\n(.*?)\n---\n", raw, re.S)
        if not match:
            continue
        metadata = {}
        for line in match[1].splitlines():
            key, sep, value = line.partition(":")
            if sep:
                metadata[key.strip()] = value.strip()
        row = {n: metadata.get(n, "unknown" if n in {"source_type", "collected_at", "effective_date"} else "")
               for n, _, _ in SPECS["documents"]["snapshots"].fields}
        row.update(filename=path.name, text=raw[match.end():].strip())
        rows.append(row)
    return rows


def catalog(user_id):
    sources = []
    for source, label, backend, scope in SOURCES:
        tables = []
        for name, spec in SPECS[source].items():
            total, state = None, "on_demand" if source == "index" else "ready"
            try:
                if source == "campus" and name == "semesters":
                    total = len(semesters.list_semesters())
                elif source in {"campus", "personal"}:
                    with sql_connection(source) as conn:
                        where = f" WHERE user_id={auth._ph()}" if source == "personal" else ""
                        total = conn.execute(f'SELECT COUNT(*) FROM "{name}"{where}',
                                             (user_id,) if source == "personal" else ()).fetchone()[0]
                elif source == "documents":
                    total = len(snapshot_rows())
            except Exception as exc:
                logger.warning("[数据浏览器] 目录读取失败: %s", type(exc).__name__)
                state = "unavailable"
            tables.append({"id": name, "label": spec.label, "description": spec.description,
                           "count": total, "state": state})
        sources.append({"id": source, "label": label, "backend": backend, "scope": scope, "tables": tables})
    return {"sources": sources, "relations": RELATIONS, "read_only": True}


def index_page(q, offset, size):
    if config.KB_BACKEND == "chroma":
        path = Path(config.CHROMA_DIR)
        if not (path / "chroma.sqlite3").is_file():
            raise StoreUnavailable("尚未发现本机 Chroma 索引；可先查看政策快照。")
        import chromadb
        client = chromadb.PersistentClient(path=str(path))
        collection = client.get_collection(config.MILVUS_COLLECTION, embedding_function=None)
        args = {"where_document": {"$contains": q}} if q else {}
        result = collection.get(limit=size + 1, offset=offset, include=["documents", "metadatas"], **args)
        rows = [{**(meta or {}), "id": key, "text": text or ""} for key, meta, text in
                zip(result["ids"], result["metadatas"], result["documents"])]
        return rows[:size], None if q else collection.count(), len(rows) > size, {
            "backend": "Chroma", "collection": config.MILVUS_COLLECTION,
            "metric": (collection.metadata or {}).get("hnsw:space", "unknown"),
        }
    if config.KB_BACKEND != "milvus":
        raise StoreUnavailable("当前向量后端不支持浏览。")
    from pymilvus import MilvusClient
    client = MilvusClient(uri=config.MILVUS_URI, db_name=config.MILVUS_DB_NAME, timeout=4)
    try:
        description = client.describe_collection(config.MILVUS_COLLECTION, timeout=4)
        fields = {f["name"]: f for f in description.get("fields", [])}
        if "text" not in fields:
            raise StoreUnavailable("目标集合没有政策正文字段，无法显示分块。")
        requested = [n for n, _, _ in SPECS["index"]["chunks"].fields]
        output = [n for n in requested if n in fields or description.get("enable_dynamic_field")]
        pattern = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        expression = "text like " + json.dumps("%" + pattern + "%", ensure_ascii=False) if q else ""
        counts = client.query(config.MILVUS_COLLECTION, filter=expression, output_fields=["count(*)"], timeout=4)
        total = int(counts[0]["count(*)"])
        rows = client.query(config.MILVUS_COLLECTION, filter=expression, output_fields=output,
                            limit=size, offset=offset, timeout=4)
        # Some driver versions nest dynamic metadata under $meta.
        rows = [{**(r.get("$meta") or {}), **r} for r in rows]
        vector = fields.get("vector", {})
        return rows, total, offset + len(rows) < total, {
            "backend": "Milvus", "collection": config.MILVUS_COLLECTION,
            "dimension": vector.get("params", {}).get("dim"),
        }
    finally:
        client.close()


def table_page(source, name, user_id, *, q="", page=1, page_size=25, sort="", direction="asc"):
    spec = SPECS.get(source, {}).get(name)
    if spec is None:
        raise MissingTable("该数据表不在浏览范围内")
    if not 1 <= page_size <= 100 or page < 1 or page * page_size > 10000:
        raise ValueError("每页 1–100 条，浏览范围最多 10000 条")
    if len(q) > 120 or direction not in {"asc", "desc"}:
        raise ValueError("搜索或排序参数无效")
    if sort and sort not in {f[0] for f in spec.fields}:
        raise ValueError("排序字段无效")
    if source == "index" and sort:
        raise ValueError("向量索引暂不提供字段排序")
    offset = (page - 1) * page_size
    info = {}
    try:
        if source in {"campus", "personal"} and name != "semesters":
            rows, total = sql_page(source, name, spec, user_id, q, offset, page_size, sort, direction)
            has_more = offset + len(rows) < total
        elif source == "documents" or (source == "campus" and name == "semesters"):
            records = snapshot_rows() if source == "documents" else semesters.list_semesters()
            all_rows = [r for r in records if not q or q.casefold() in " ".join(str(r.get(f[0], "")) for f in spec.fields).casefold()]
            field = sort or spec.primary[0]
            all_rows.sort(key=lambda r: (r.get(field) is None, r.get(field) if isinstance(r.get(field), (int, float))
                                        else str(r.get(field, "")).casefold()), reverse=direction == "desc")
            total = len(all_rows)
            rows = all_rows[offset:offset + page_size]
            has_more = offset + len(rows) < total
        else:
            rows, total, has_more, info = index_page(q, offset, page_size)
        # Only the display projection leaves this module, including for vector results.
        names = [f[0] for f in spec.fields]
        safe_rows = []
        for row in rows:
            safe = {n: row.get(n) for n in names}
            truncated = [n for n, v in safe.items() if isinstance(v, str) and len(v) > 20000]
            for n in truncated:
                safe[n] = safe[n][:20000]
            safe["_truncated"] = truncated
            safe_rows.append(safe)
        return {"source": source, "table": name, "label": spec.label, "description": spec.description,
                "columns": columns(spec), "rows": safe_rows, "total": total, "page": page,
                "page_size": page_size, "has_more": has_more, "sortable": source != "index", "info": info}
    except StoreUnavailable:
        raise
    except Exception as exc:
        logger.warning("[数据浏览器] 数据读取失败: %s", type(exc).__name__)
        message = ("向量索引暂不可用。请确认本机服务和目标集合已就绪，或先查看政策快照。"
                   if source == "index" else "数据暂不可用，请确认本机数据库已初始化后重试。")
        raise StoreUnavailable(message) from exc
