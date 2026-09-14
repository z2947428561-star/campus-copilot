"""课表与空教室查询工具。

空教室原理:全量教室减去「同天同时段且周范围覆盖目标周」的占用记录。
对应验收场景:"明天上午哪个教室空着""周三10点找教室自习"
"""
import sqlite3

from langchain_core.tools import tool

DB_PATH = "data/campus.db"
PERIODS = ["08:30-10:00", "10:15-11:45", "12:00-13:30", "14:00-15:30", "15:45-17:15"]
WEEKDAY_CN = {1: "周一", 2: "周二", 3: "周三", 4: "周四", 5: "周五"}


def _week_covers(weeks: str, week_no: int) -> bool:
    """"1-14" 或 "6-14" 形式的周范围是否覆盖 week_no"""
    lo, hi = weeks.split("-")
    return int(lo) <= week_no <= int(hi)


@tool
def find_empty_classrooms(weekday: int, period: str, week_no: int = 1) -> str:
    """查询某天某时段 Block A 的空闲教室(含类型与容量,大教室优先)。

    适用于:"周三上午 10 点哪有空教室""周五下午找地方自习"。
    若用户说"上午",请用具体时段(如 10:15-11:45)调用,别传模糊词。

    Args:
        weekday: 星期几,1=周一 ... 5=周五(周末无排课数据)
        period: 时段,可选值:08:30-10:00 / 10:15-11:45 / 12:00-13:30 / 14:00-15:30 / 15:45-17:15
        week_no: 目标教学周次(默认 1),用于匹配排课周范围(部分课程只在 6-14 周开课)
    """
    if period not in PERIODS:
        return f"时段无效,period 只能是:{' / '.join(PERIODS)}"
    if not 1 <= weekday <= 5:
        return "weekday 需在 1-5 之间(周一至周五)。"

    conn = sqlite3.connect(DB_PATH)
    occupied_rows = conn.execute(
        "SELECT room, weeks, course_id FROM timetable WHERE weekday = ? AND period = ?",
        (weekday, period),
    ).fetchall()
    occupied = {room for room, weeks, _ in occupied_rows if _week_covers(weeks, week_no)}
    all_rooms = conn.execute(
        "SELECT room_id, type, capacity FROM classrooms ORDER BY capacity DESC"
    ).fetchall()
    conn.close()

    free = [(rid, t, cap) for rid, t, cap in all_rooms if rid not in occupied]
    if not free:
        return f"{WEEKDAY_CN[weekday]} {period}(第 {week_no} 周)Block A 无空闲教室,全部被排课。"

    lines = [f"{WEEKDAY_CN[weekday]} {period}(第 {week_no} 周)Block A 空闲教室 {len(free)} 间:"]
    lines += [f"  {rid}({t},{cap} 座)" for rid, t, cap in free]
    return "\n".join(lines)


@tool
def query_course_schedule(course_id: str) -> str:
    """查询某门课的上课时间和地点。

    Args:
        course_id: 课程代码,如 CS101(大小写均可)
    """
    cid = course_id.strip().upper()
    conn = sqlite3.connect(DB_PATH)
    name = conn.execute("SELECT name FROM courses WHERE course_id = ?", (cid,)).fetchone()
    if not name:
        conn.close()
        return f"课程库中不存在课程 {cid},可用 query_course 工具按名称搜索。"
    rows = conn.execute(
        "SELECT room, weekday, period, weeks FROM timetable WHERE course_id = ? ORDER BY weekday, period",
        (cid,),
    ).fetchall()
    conn.close()
    if not rows:
        return f"{cid} {name[0]} 本学期(九月学期)未排课(Block A 无记录)。"

    lines = [f"{cid} {name[0]} 上课时间:"]
    lines += [f"  {WEEKDAY_CN[w]} {p},{room}(第 {wk} 周)" for room, w, p, wk in rows]
    return "\n".join(lines)
