"""课表与空教室查询工具。

空教室原理:全量教室减去「同天同时段且周范围覆盖目标周」的占用记录。
对应验收场景:"明天上午哪个教室空着""周三10点找教室自习"

课程对应:
    第05章 §3.1(p16-18) parse_docstring
    第05章 §3.3(p20-27) args_schema —— 本工具的 weekday/period 是典型
        "需要枚举值与范围限制"的场景;加了 schema 后非法值会在函数体
        执行前被 Pydantic 拦下(ValidationError, type=literal_error)
    第05章 §6.4(p43)    工具返回字符串而非 dict
"""
import json
import sqlite3

from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime

from context import UserContext
from student_data import list_courses

from .schemas import EmptyClassroomInput, PERIOD_VALUES

DB_PATH = "data/campus.db"
PERIODS = list(PERIOD_VALUES)
WEEKDAY_CN = {1: "周一", 2: "周二", 3: "周三", 4: "周四", 5: "周五"}


def _week_covers(weeks: str, week_no: int) -> bool:
    """"1-14" 或 "6-14" 形式的周范围是否覆盖 week_no"""
    lo, hi = weeks.split("-")
    return int(lo) <= week_no <= int(hi)


def _dump(payload: dict) -> str:
    # 第05章 §6.4(p43):返回 str;ensure_ascii=False 避免中文被转成 \uXXXX
    return json.dumps(payload, ensure_ascii=False)


@tool(
    parse_docstring=True,
    args_schema=EmptyClassroomInput,
    description=(
        "查询某天某时段 Block A 的空闲教室(含类型与容量,大教室优先)。"
        "适用于「周三上午 10 点哪有空教室」「周五下午找地方自习」。"
        "用户说「上午」请选 10:15-11:45,说「下午」请选 14:00-15:30。"
    ),
)
def find_empty_classrooms(weekday: int, period: str, week_no: int = 1) -> str:
    """查询 Block A 的空闲教室。

    Args:
        weekday: 星期几,1=周一 ... 5=周五。
        period: 时段,可选值见 schemas.PERIOD_VALUES。
        week_no: 目标教学周次(默认 1),用于匹配排课周范围。

    Returns:
        该时段空闲教室的 JSON 字符串(含 count 与 rooms 列表,每项有
        room/type/capacity);若无空闲教室则 count 为 0 并附 note 说明。
    """
    # weekday / period / week_no 的合法性已由 EmptyClassroomInput 保证
    # (第05章 §3.3 p23-24:非法值在函数体执行前抛 ValidationError),
    # 旧版这里的两段手工校验分支因此可以删掉。
    conn = sqlite3.connect(DB_PATH)
    try:
        occupied_rows = conn.execute(
            "SELECT room, weeks FROM timetable WHERE weekday = ? AND period = ?",
            (weekday, period),
        ).fetchall()
        all_rooms = conn.execute(
            "SELECT room_id, type, capacity FROM classrooms ORDER BY capacity DESC"
        ).fetchall()
    finally:
        conn.close()

    occupied = {room for room, weeks in occupied_rows if _week_covers(weeks, week_no)}
    free = [(rid, t, cap) for rid, t, cap in all_rooms if rid not in occupied]

    payload = {
        "building": "Block A",
        "weekday": weekday,
        "weekday_cn": WEEKDAY_CN[weekday],
        "period": period,
        "week_no": week_no,
        "count": len(free),
        "rooms": [{"room": rid, "type": t, "capacity": cap} for rid, t, cap in free],
    }
    if not free:
        payload["note"] = (
            f"{WEEKDAY_CN[weekday]} {period}(第 {week_no} 周)全部教室均被排课占用"
        )
    return _dump(payload)


@tool(
    parse_docstring=True,
    description="查询某门课的上课时间和地点(输入课程代码,如 CS101)。",
)
def query_course_schedule(course_id: str) -> str:
    """查询某门课的上课时间与地点。

    Args:
        course_id: 课程代码,如 CS101(大小写均可)。

    Returns:
        该课程各时段的 JSON 字符串(含 course_id/name/semester 与 sessions
        列表,每项有 weekday/weekday_cn/period/room/weeks);课程不在库或
        本学期未排课时返回带 error 或 note 的 JSON 字符串。
    """
    cid = course_id.strip().upper()
    conn = sqlite3.connect(DB_PATH)
    try:
        row = conn.execute(
            "SELECT name FROM courses WHERE course_id = ?", (cid,)
        ).fetchone()
        if not row:
            return _dump(
                {
                    "course_id": cid,
                    "error": "课程库中不存在该课程",
                    "note": "可用 query_course 工具按课程名关键词搜索",
                }
            )
        rows = conn.execute(
            "SELECT room, weekday, period, weeks FROM timetable WHERE course_id = ? "
            "ORDER BY weekday, period",
            (cid,),
        ).fetchall()
    finally:
        conn.close()

    payload = {
        "course_id": cid,
        "name": row[0],
        "semester": "September Semester 2026",
        "sessions": [
            {
                "weekday": w,
                "weekday_cn": WEEKDAY_CN[w],
                "period": p,
                "room": room,
                "weeks": wk,
            }
            for room, w, p, wk in rows
        ],
    }
    if not rows:
        payload["note"] = "本学期(九月学期)在 Block A 无排课记录"
    return _dump(payload)


@tool(description="查询当前登录用户自己已选课程的课表；用户问『我的课表』『我今天有什么课』时使用。")
def query_my_schedule(runtime: ToolRuntime[UserContext]) -> str:
    """读取当前用户已添加课程的时间与教室。"""
    user_id = (runtime.context.user_id or "").strip() if runtime.context else ""
    if not user_id:
        return _dump({"ok": False, "error": "缺少用户身份，无法读取个人课表"})
    try:
        courses = list_courses(user_id)
    except Exception as e:
        return _dump({"ok": False, "error": f"读取个人课表失败: {e}"})
    return _dump({"ok": True, "semester": "September Semester 2026", "courses": courses,
                  "note": "这是用户自行添加的课程和演示排课，并非学校实时选课系统"})
