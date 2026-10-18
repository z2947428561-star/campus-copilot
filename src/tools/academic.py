"""Calendar tools scoped by recorded semester, never a hard-coded week count."""
from datetime import date
import json

from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime

from context import UserContext
import semesters
from .schemas import AcademicWeekInput


@tool(description="列出已录入学期的 ID、日期范围、版本与排课状态；查询其他学期前可先调用。")
def list_available_semesters() -> str:
    """List recorded academic semesters; no future calendar is inferred."""
    keys = ("semester_id", "label", "start_date", "end_date", "version", "schedule_status", "is_demo")
    return json.dumps({"semesters": [{k: t[k] for k in keys} for t in semesters.list_semesters()]}, ensure_ascii=False)


@tool(parse_docstring=True, args_schema=AcademicWeekInput,
      description="按日期查询已录入学期的教学周、复习、考试或假期；返回实际学期与数据版本，缺校历时说明无法确认。")
def get_academic_week(date_str: str = "", semester_id: str = "", runtime: ToolRuntime[UserContext] = None) -> str:
    """查询所选日期的学期阶段。

    Args:
        date_str: YYYY-MM-DD；留空使用校园今天。
        semester_id: 显式限定学期；留空时按日期或运行上下文选择。

    Returns:
        标明学期、资料版本和实际教学周数的说明；未覆盖日期时明确说明。
    """
    try:
        day = date.fromisoformat(date_str) if date_str.strip() else semesters.campus_today()
        context_id = getattr(getattr(runtime, "context", None), "semester_id", None) if not date_str.strip() else None
        term = semesters.resolve_date(day.isoformat(), semester_id or context_id)
        with semesters.catalog_connection() as conn:
            weeks = semesters.term_rows(conn, "calendar_weeks", term)
            events = semesters.term_rows(conn, "semester_events", term)
    except (ValueError, OSError) as exc:
        return "校历未能确认：" + str(exc)
    prefix = f"{day.isoformat()} · {term['label']} [{term['semester_id']}] · 数据版本 {term['version']}。"
    if not term["start_date"] <= day.isoformat() <= term["end_date"]:
        return prefix + f"日期超出该学期已录范围（{term['start_date']} 至 {term['end_date']}），无法确认阶段。"
    week = next((w for w in weeks if w["start"] <= day.isoformat() <= w["end"]), None)
    names = {"revision": "复习周", "exam": "考试周", "break": "学期假期", "registration": "注册", "orientation": "迎新"}
    current_events = [e for e in events if e["start_date"] <= day.isoformat() <= (e["end_date"] or e["start_date"])]
    if week:
        result = f"第 {week['week_no']} 教学周（已录入共 {len(weeks)} 周）。"
    elif current_events:
        result = "处于" + "、".join(names.get(e["event_type"], e["name"]) for e in current_events) + "。"
    elif weeks and day.isoformat() < min(w["start"] for w in weeks):
        result = "尚未进入已录入的教学周。"
    else:
        result = "该日期的具体阶段未录入，无法确认。"
    future = sorted([e for e in events if e["event_type"] in {"revision", "exam", "break"}
                     and e["start_date"] > day.isoformat()], key=lambda e: e["start_date"])
    for event in future:
        remaining = (date.fromisoformat(event["start_date"]) - day).days
        result += f"距{names[event['event_type']]}（{event['start_date']}）还有 {remaining} 天。"
    if term["is_demo"]:
        result += "资料含演示配置，非实时学校系统。"
    return prefix + result
