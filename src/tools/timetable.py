"""Semester-scoped timetable and room occupancy, with explicit data coverage."""
import json

from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime
from context import UserContext
from student_data import list_courses
import semesters
from .schemas import EmptyClassroomInput, PERIOD_VALUES

PERIODS = list(PERIOD_VALUES)
WEEKDAY_CN = {1: "周一", 2: "周二", 3: "周三", 4: "周四", 5: "周五"}


def _week_covers(weeks: str, week_no: int) -> bool:
    lo, hi = weeks.split("-")
    return int(lo) <= week_no <= int(hi)


def _dump(payload):
    return json.dumps(payload, ensure_ascii=False)


def _period_overlaps(left, right):
    start, end = left.split("-")
    other_start, other_end = right.split("-")
    return start < other_end and other_start < end


def _scope(term):
    return {"semester_id": term["semester_id"], "semester": term["label"],
            "data_version": term["version"], "schedule_status": term["schedule_status"]}


@tool(parse_docstring=True, args_schema=EmptyClassroomInput,
      description="按所选学期、教学周与时段查询已录入教室的空闲情况；未录入排课时不能确认空闲。上午选 10:15-11:45，下午选 14:00-15:30。")
def find_empty_classrooms(weekday: int, period: str, week_no: int = 1, semester_id: str = "",
                          runtime: ToolRuntime[UserContext] = None) -> str:
    """查询所选学期中某时段的空闲教室。

    Args:
        weekday: 星期几，1 至 5。
        period: 精确上课时段。
        week_no: 所选学期的教学周次。
        semester_id: 显式学期 ID；留空使用运行上下文。

    Returns:
        带学期与资料版本的 JSON；缺少排课或教学周时 ok=false。
    """
    try:
        term = semesters.selected_semester(semester_id, runtime)
        with semesters.catalog_connection() as conn:
            weeks = semesters.term_rows(conn, "calendar_weeks", term)
            if term["schedule_status"] == "unavailable":
                return _dump({"ok": False, **_scope(term), "error": "该学期尚未录入排课，无法确认空闲教室"})
            if week_no not in {w["week_no"] for w in weeks}:
                return _dump({"ok": False, **_scope(term), "error": "目标教学周未录入，无法确认空闲教室"})
            rows = semesters.term_rows(conn, "timetable", term)
            all_rooms = conn.execute("SELECT room_id,type,capacity FROM classrooms ORDER BY capacity DESC,room_id").fetchall()
        occupied = {r["room"] for r in rows if r["weekday"] == weekday and _period_overlaps(r["period"], period)
                    and _week_covers(r["weeks"], week_no)}
        free = [{"room": rid, "type": kind, "capacity": cap} for rid, kind, cap in all_rooms if rid not in occupied]
        return _dump({"ok": True, **_scope(term), "weekday": weekday, "weekday_cn": WEEKDAY_CN[weekday],
            "period": period, "week_no": week_no, "count": len(free), "rooms": free,
            "note": "依据该学期已录排课推算，非实时占用；演示数据不代表学校实际安排。"})
    except ValueError as exc:
        return _dump({"ok": False, "error": str(exc)})


@tool(parse_docstring=True, description="查询课程在所选学期的上课时间与教室，输入课程代码；返回学期、版本和排课覆盖状态。")
def query_course_schedule(course_id: str, semester_id: str = "", runtime: ToolRuntime[UserContext] = None) -> str:
    """查询某门课在明确学期的课表。

    Args:
        course_id: 课程代码。
        semester_id: 显式学期 ID；留空使用运行上下文。

    Returns:
        课表 JSON；未录入该学期排课时明确说明。
    """
    cid = course_id.strip().upper()
    try:
        term = semesters.selected_semester(semester_id, runtime)
        with semesters.catalog_connection() as conn:
            row = conn.execute("SELECT name FROM courses WHERE course_id=?", (cid,)).fetchone()
            if row is None:
                return _dump({"ok": False, **_scope(term), "error": "课程库中不存在该课程"})
            rows = [r for r in semesters.term_rows(conn, "timetable", term) if r["course_id"] == cid]
        sessions = [{k: r[k] for k in ("room", "weekday", "period", "weeks")} for r in
                    sorted(rows, key=lambda r: (r["weekday"], r["period"], r["room"]))]
        for session in sessions:
            session["weekday_cn"] = WEEKDAY_CN[session["weekday"]]
        return _dump({"ok": term["schedule_status"] != "unavailable", **_scope(term),
            "course_id": cid, "name": row[0], "sessions": sessions,
            "note": "该学期未录入排课，无法确认上课安排" if term["schedule_status"] == "unavailable"
                    else "仅反映该学期已录入记录；无记录不能推断课程未开设。"})
    except ValueError as exc:
        return _dump({"ok": False, "error": str(exc)})


@tool(description="查询当前登录用户在所选学期自行添加课程的课表；其他学期可显式传 semester_id。")
def query_my_schedule(runtime: ToolRuntime[UserContext], semester_id: str = "") -> str:
    """Read only this user's selected-semester courses and schedule."""
    user_id = getattr(getattr(runtime, "context", None), "user_id", "")
    if not user_id:
        return _dump({"ok": False, "error": "缺少用户身份，无法读取个人课表"})
    try:
        term = semesters.selected_semester(semester_id, runtime)
        courses = list_courses(user_id, term["semester_id"])
        return _dump({"ok": True, **_scope(term), "courses": courses,
            "note": "这是所选学期自行添加的课程。" + ("排课尚未录入。" if term["schedule_status"] == "unavailable" else "排课含演示数据，非学校实时系统。")})
    except ValueError as exc:
        return _dump({"ok": False, "error": str(exc)})
