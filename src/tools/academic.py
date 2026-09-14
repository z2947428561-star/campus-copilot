"""教学周查询工具:今天是第几教学周、距考试/放假还有多久。

对应验收场景:"现在第几教学周""还有多久考试""什么时候放假"
"""
import sqlite3
from datetime import date

from langchain_core.tools import tool

DB_PATH = "data/campus.db"


def _fmt(d: str) -> str:
    """2026-09-25 -> 9月25日"""
    y, m, dd = d.split("-")
    return f"{int(m)}月{int(dd)}日"


@tool
def get_academic_week(date_str: str = "") -> str:
    """查询某日期处于 XMUM 九月学期的什么状态:第几教学周,以及距复习周、考试周、学期结束还有多久。

    适用于:"现在第几教学周""还有多久考试""什么时候放假""开学了吗"。

    Args:
        date_str: 查询日期,格式 YYYY-MM-DD。留空默认为今天。
    """
    d = date.fromisoformat(date_str) if date_str.strip() else date.today()
    conn = sqlite3.connect(DB_PATH)

    # 1) 是否在某教学周内
    row = conn.execute(
        "SELECT week_no, start, end FROM calendar_weeks WHERE start <= ? AND end >= ?",
        (d.isoformat(), d.isoformat()),
    ).fetchone()

    # 2) 取复习周/考试周日期,用于倒计时
    rev = conn.execute(
        "SELECT start_date, end_date FROM semester_events WHERE event_type='revision'"
    ).fetchone()
    exam = conn.execute(
        "SELECT start_date, end_date FROM semester_events WHERE event_type='exam'"
    ).fetchone()
    brk = conn.execute(
        "SELECT start_date, end_date FROM semester_events WHERE event_type='break'"
    ).fetchone()
    reg = conn.execute(
        "SELECT MIN(start_date) FROM semester_events WHERE event_type='registration'"
    ).fetchone()
    wk1 = conn.execute("SELECT start FROM calendar_weeks WHERE week_no=1").fetchone()
    wk14 = conn.execute("SELECT end FROM calendar_weeks WHERE week_no=14").fetchone()
    conn.close()

    def days_to(s: str) -> int:
        return (date.fromisoformat(s) - d).days

    if row:
        week_no, _, _ = row
        return (
            f"{_fmt(d.isoformat())}是九月学期第 {week_no} 教学周(共 14 周)。"
            f"距复习周({_fmt(rev[0])})还有 {days_to(rev[0])} 天,"
            f"距考试周({_fmt(exam[0])})还有 {days_to(exam[0])} 天,"
            f"学期于 {_fmt(wk14[0])} 结束,随后进入学期假期({ _fmt(brk[0])} 起)。"
        )

    # 不在教学周:判断处于哪个阶段
    if d < date.fromisoformat(reg[0]):
        return (
            f"{_fmt(d.isoformat())}距九月学期注册日({_fmt(reg[0])})还有 {days_to(reg[0])} 天,"
            f"课程于 {_fmt(wk1[0])}(第 1 教学周)正式开始。"
        )
    if date.fromisoformat(rev[0]) <= d <= date.fromisoformat(rev[1]):
        return f"{_fmt(d.isoformat())}处于复习周({_fmt(rev[0])} - {_fmt(rev[1])}),考试周 {_fmt(exam[0])} 开始。"
    if date.fromisoformat(exam[0]) <= d <= date.fromisoformat(exam[1]):
        return f"{_fmt(d.isoformat())}处于考试周({_fmt(exam[0])} - {_fmt(exam[1])}),学期假期 {_fmt(brk[0])} 开始。"
    if date.fromisoformat(brk[0]) <= d <= date.fromisoformat(brk[1]):
        return f"{_fmt(d.isoformat())}处于学期假期({_fmt(brk[0])} - {_fmt(brk[1])})。"
    if date.fromisoformat(reg[0]) <= d < date.fromisoformat(wk1[0]):
        return f"{_fmt(d.isoformat())}处于注册迎新阶段,课程将于 {_fmt(wk1[0])}(第 1 教学周)开始。"
    return f"{_fmt(d.isoformat())}不在九月学期(2026-09-25 至 2027-02-11)范围内,请确认日期。"
