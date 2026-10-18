"""Semester identity, legacy read compatibility and atomic public-data imports."""
from contextlib import closing, contextmanager
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3

from pydantic import BaseModel, ConfigDict, Field, model_validator


def campus_today():
    return datetime.now(timezone(timedelta(hours=8))).date()


def catalog_path():
    # Lazy import avoids a cycle; existing callers/tests can still configure this path.
    from student_data import CATALOG_DB
    return Path(CATALOG_DB)


@contextmanager
def catalog_connection(path=None, *, write=False):
    target = Path(path) if path is not None else catalog_path()
    uri = target.resolve().as_uri() + ("?mode=rw" if write else "?mode=ro")
    with closing(sqlite3.connect(uri, uri=True, timeout=5)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        if not write:
            conn.execute("PRAGMA query_only=ON")
        yield conn


def has_column(conn, table, column):
    # Only internal fixed table names cross this seam.
    return any(row[1] == column for row in conn.execute(f'PRAGMA table_info("{table}")'))


def _exists(conn, name):
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


class Week(BaseModel):
    model_config = ConfigDict(extra="forbid")
    week_no: int = Field(ge=1, le=54)
    start: date
    end: date
    type: str = Field(default="teaching", min_length=1, max_length=30)


class Event(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    event_type: str = Field(min_length=1, max_length=40)
    start_date: date
    end_date: date | None = None


class Session(BaseModel):
    model_config = ConfigDict(extra="forbid")
    course_id: str | None = Field(default=None, min_length=1, max_length=64)
    room: str = Field(min_length=1, max_length=64)
    weekday: int = Field(ge=1, le=5)
    period: str = Field(pattern=r"^\d{2}:\d{2}-\d{2}:\d{2}$")
    weeks: str = Field(pattern=r"^\d{1,2}-\d{1,2}$")


class SemesterImport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    semester_id: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    label: str = Field(min_length=1, max_length=120)
    academic_year: str = Field(min_length=1, max_length=40)
    start_date: date
    end_date: date
    source: str = Field(default="", max_length=1000)
    is_demo: bool = True
    weeks: list[Week] = Field(default_factory=list, max_length=54)
    events: list[Event] = Field(default_factory=list, max_length=500)
    timetable: list[Session] | None = Field(default=None, max_length=10000)

    @model_validator(mode="after")
    def coherent_dates(self):
        date.fromisoformat(self.semester_id + "-01")
        if self.end_date < self.start_date:
            raise ValueError("学期结束日期不能早于开始日期")
        ordered = sorted(self.weeks, key=lambda w: w.week_no)
        if [w.week_no for w in ordered] != list(range(1, len(ordered) + 1)):
            raise ValueError("教学周须从 1 连续编号且不重复")
        previous = None
        for week in ordered:
            if not self.start_date <= week.start <= week.end <= self.end_date:
                raise ValueError("教学周日期须落在学期范围内")
            if previous and week.start <= previous:
                raise ValueError("同一学期的教学周不能重叠或倒序")
            previous = week.end
        for event in self.events:
            if not self.start_date <= event.start_date <= (event.end_date or event.start_date) <= self.end_date:
                raise ValueError("事件日期须落在学期范围内")
        for session in self.timetable or []:
            lo, hi = map(int, session.weeks.split("-"))
            if not 1 <= lo <= hi <= len(self.weeks):
                raise ValueError("排课周范围必须被已录入的教学周覆盖")
            start, end = session.period.split("-")
            try:
                start_time, end_time = datetime.strptime(start, "%H:%M"), datetime.strptime(end, "%H:%M")
            except ValueError as exc:
                raise ValueError("排课时段无效") from exc
            if start_time >= end_time:
                raise ValueError("排课结束时间须晚于开始时间")
        return self


def _hash(payload):
    data = payload.model_dump(mode="json")
    for key in ("weeks", "events", "timetable"):
        if data[key] is not None:
            data[key] = sorted(data[key], key=lambda r: json.dumps(r, sort_keys=True))
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _legacy_payload(conn):
    if not _exists(conn, "calendar_weeks"):
        return None
    names = conn.execute("SELECT DISTINCT semester,academic_year FROM calendar_weeks").fetchall()
    if not names:
        if _exists(conn, "timetable") and conn.execute("SELECT COUNT(*) FROM timetable").fetchone()[0]:
            raise ValueError("旧排课缺少可确定的学期校历，无法自动归属")
        return None
    if len(names) != 1:
        raise ValueError("旧库混有多个学期且排课无归属，请先人工确认")
    label, year = names[0]
    weeks = [dict(r) for r in conn.execute('SELECT week_no,start,end,type FROM calendar_weeks ORDER BY week_no')]
    events = [dict(r) for r in conn.execute('SELECT name,event_type,start_date,end_date FROM semester_events')]
    sessions = [dict(r) for r in conn.execute('SELECT course_id,room,weekday,period,weeks FROM timetable')]
    starts = [w["start"] for w in weeks] + [e["start_date"] for e in events]
    ends = [w["end"] for w in weeks] + [e["end_date"] or e["start_date"] for e in events]
    return SemesterImport(semester_id=min(starts)[:7], label=label, academic_year=year or "unknown",
        start_date=min(starts), end_date=max(ends), weeks=weeks, events=events, timetable=sessions, is_demo=True)


def _record(payload, *, storage_key=None, version=1, legacy=False):
    return {"semester_id": payload.semester_id, "label": payload.label, "academic_year": payload.academic_year,
        "start_date": payload.start_date.isoformat(), "end_date": payload.end_date.isoformat(),
        "storage_key": storage_key or payload.semester_id, "version": version, "data_hash": _hash(payload),
        "schedule_status": "unavailable" if payload.timetable is None else "recorded",
        "source": payload.source, "is_demo": payload.is_demo, "legacy": legacy}


def list_semesters(path=None):
    target = Path(path) if path is not None else catalog_path()
    if not target.is_file():
        return []
    with catalog_connection(target) as conn:
        if _exists(conn, "semesters"):
            return [{**dict(row), "is_demo": bool(row["is_demo"]), "legacy": False}
                    for row in conn.execute("SELECT * FROM semesters ORDER BY start_date,semester_id")]
        payload = _legacy_payload(conn)
        return [_record(payload, storage_key=payload.label, legacy=True)] if payload else []


def resolve_semester(semester_id=None, *, path=None):
    terms = list_semesters(path)
    if semester_id:
        matches = [t for t in terms if semester_id in {t["semester_id"], t["storage_key"]}]
        if len(matches) != 1:
            raise ValueError("学期未录入，请先查看可用学期")
        return matches[0]
    today = campus_today().isoformat()
    active = [t for t in terms if t["start_date"] <= today <= t["end_date"]]
    if len(active) > 1:
        raise ValueError("当前日期落在多个学期范围内，请明确选择学期")
    if active:
        return active[0]
    past = [t for t in terms if t["start_date"] <= today]
    if terms:
        return (past or terms)[-1 if past else 0]
    raise ValueError("尚未录入学期校历")


def resolve_date(date_str, semester_id=None, *, path=None):
    day = date.fromisoformat(date_str).isoformat()
    if semester_id:
        return resolve_semester(semester_id, path=path)
    matches = [t for t in list_semesters(path) if t["start_date"] <= day <= t["end_date"]]
    if len(matches) != 1:
        raise ValueError("该日期未被唯一一份已录入学期校历覆盖，请明确学期或补充校历")
    return matches[0]


def selected_semester(semester_id=None, runtime=None):
    context = getattr(runtime, "context", None)
    return resolve_semester(semester_id or getattr(context, "semester_id", None))


def term_rows(conn, table, term):
    if table not in {"calendar_weeks", "semester_events", "timetable"}:
        raise ValueError("不支持的学期数据表")
    where = " WHERE semester_id=?" if has_column(conn, table, "semester_id") else ""
    return [dict(r) for r in conn.execute(f'SELECT * FROM "{table}"{where}', (term["semester_id"],) if where else ())]


def _write_registry(conn, record):
    keys = ("semester_id", "label", "academic_year", "start_date", "end_date", "storage_key", "version",
            "data_hash", "schedule_status", "source", "is_demo")
    conn.execute("INSERT INTO semesters (" + ",".join(keys) + ") VALUES (" + ",".join("?" for _ in keys) + ") "
                 "ON CONFLICT(semester_id) DO UPDATE SET " + ",".join(k + "=excluded." + k for k in keys[1:]),
                 tuple(record[k] for k in keys))


def _migrate(conn):
    if _exists(conn, "semesters"):
        return False
    payload = _legacy_payload(conn)
    conn.execute("""CREATE TABLE semesters (
        semester_id TEXT PRIMARY KEY, label TEXT NOT NULL, academic_year TEXT NOT NULL,
        start_date TEXT NOT NULL, end_date TEXT NOT NULL, storage_key TEXT NOT NULL UNIQUE,
        version INTEGER NOT NULL, data_hash TEXT NOT NULL, schedule_status TEXT NOT NULL,
        source TEXT NOT NULL, is_demo INTEGER NOT NULL)""")
    legacy_id = payload.semester_id if payload else ""
    conn.execute("""CREATE TABLE calendar_weeks_new (
        semester_id TEXT NOT NULL REFERENCES semesters(semester_id), week_no INTEGER NOT NULL,
        semester TEXT NOT NULL, academic_year TEXT, start TEXT NOT NULL, end TEXT NOT NULL,
        type TEXT NOT NULL, PRIMARY KEY(semester_id,week_no))""")
    if payload:
        _write_registry(conn, _record(payload, storage_key=payload.label))
        conn.execute("INSERT INTO calendar_weeks_new SELECT ?,week_no,semester,academic_year,start,end,type FROM calendar_weeks", (legacy_id,))
    conn.execute("DROP TABLE calendar_weeks")
    conn.execute("ALTER TABLE calendar_weeks_new RENAME TO calendar_weeks")
    for table in ("timetable", "semester_events"):
        # legacy_id is validated YYYY-MM by SemesterImport (or empty for empty tables).
        conn.execute(f"ALTER TABLE {table} ADD COLUMN semester_id TEXT NOT NULL DEFAULT '{legacy_id}'")
        conn.execute(f"CREATE INDEX idx_{table}_semester ON {table}(semester_id)")
    return True


def migrate_catalog(path=None):
    with catalog_connection(path, write=True) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        changed = _migrate(conn)
    return {"migrated": changed}


def import_semester(data, path=None, *, expected_version=None):
    payload = SemesterImport.model_validate(data)
    with catalog_connection(path, write=True) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        _migrate(conn)
        old = conn.execute("SELECT * FROM semesters WHERE semester_id=?", (payload.semester_id,)).fetchone()
        if old and old["data_hash"] == _hash(payload):
            return dict(old)
        if old and expected_version != old["version"]:
            raise ValueError("学期数据已存在或版本变化；请核对后提供 expected_version")
        for session in payload.timetable or []:
            if session.course_id is not None and not conn.execute("SELECT 1 FROM courses WHERE course_id=?", (session.course_id,)).fetchone():
                raise ValueError("排课引用不存在的课程：" + session.course_id)
            if not conn.execute("SELECT 1 FROM classrooms WHERE room_id=?", (session.room,)).fetchone():
                raise ValueError("排课引用不存在的教室：" + session.room)
        record = _record(payload, storage_key=old["storage_key"] if old else None,
                         version=old["version"] + 1 if old else 1)
        _write_registry(conn, record)
        for table in ("calendar_weeks", "semester_events", "timetable"):
            conn.execute(f"DELETE FROM {table} WHERE semester_id=?", (payload.semester_id,))
        conn.executemany("INSERT INTO calendar_weeks VALUES (?,?,?,?,?,?,?)", [
            (payload.semester_id, w.week_no, payload.label, payload.academic_year,
             w.start.isoformat(), w.end.isoformat(), w.type) for w in payload.weeks])
        conn.executemany("INSERT INTO semester_events(name,event_type,start_date,end_date,semester_id) VALUES (?,?,?,?,?)", [
            (e.name, e.event_type, e.start_date.isoformat(), e.end_date.isoformat() if e.end_date else None, payload.semester_id)
            for e in payload.events])
        conn.executemany("INSERT INTO timetable(room,weekday,period,course_id,weeks,semester_id) VALUES (?,?,?,?,?,?)", [
            (s.room, s.weekday, s.period, s.course_id, s.weeks, payload.semester_id) for s in payload.timetable or []])
    return record
