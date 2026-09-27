"""GPA 计算与分析工具。

课程对应:
    第06章 §2.1(p2-5)   Pydantic 模型定义规范:"必须继承 BaseModel + 类型提示 +
                        Field(description=...)","没有描述,LLM 可能格式错误"
    第06章 §2.1.2(p15-16) 限制条件(ge/le)+ ValidationError
    第05章 §6.4(p43)    工具返回字符串而不是 dict:✅ json.dumps(..., ensure_ascii=False)
    第05章 §6.3(p42-43) 工具失败三层防护之第 1 层:工具内 try/except 返回错误信息
    第09章 §4.2(p74-80) 工具内读写长期记忆(context 注入版)

一处必须在答辩时说清楚的术语问题:
    本工具**不是**第06章讲的"结构化输出"。第06章的结构化输出指
    `with_structured_output()`(让**模型**产出结构);Agent 层对应的是
    第07章 §7(p35-39)的 `response_format=ToolStrategy(...)`。
    本工具的 GPA 是 **Python 确定性算出来的**,Pydantic 在这里的作用是
    "内部数据契约 + 序列化前的类型校验",而不是让模型填字段。
    所以准确说法是:"Pydantic 数据契约 + 工具返回值序列化"。
    (旧版 docstring 写"Pydantic 结构化输出"并与"课程对应 P41-50"挂钩,
     这两处都不准确:P41-50 是第07章 ToolStrategy 的 schema 演示。)
"""
import json
import logging

from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime
from pydantic import BaseModel, Field

from context import UserContext
from student_data import list_grades

logger = logging.getLogger("campus")



def _dump(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


class CourseGrade(BaseModel):
    """单门课程的成绩记录(第06章 §2.1 p3-5:字段必须有 description)。"""

    course_id: str = Field(description="课程代码,如 CS101")
    name: str = Field(description="课程英文名称")
    credits: float = Field(gt=0, description="学分,大于 0")
    grade_point: float = Field(ge=0, le=4.0, description="绩点,范围 0-4.0(XMUM 4.0 制)")
    letter: str = Field(description="字母等级,如 A / A- / B+")


class GpaReport(BaseModel):
    """GPA 分析报告(嵌套结构,第06章 §2.1.2 p12-14 建议嵌套不超过 3 层)。"""

    total_credits: float = Field(gt=0, description="本学期总学分")
    weighted_gpa: float = Field(ge=0, le=4.0, description="学分加权平均绩点")
    strongest: CourseGrade = Field(description="绩点最高的课程")
    weakest: CourseGrade = Field(description="绩点最低的课程(主要拖累项)")
    level: str = Field(description="绩点等级:优秀 / 良好 / 预警")
    advice: str = Field(description="针对当前绩点的改进建议,中文一句话")


def _load_grades(user_id: str) -> list[CourseGrade]:
    rows = list_grades(user_id)
    missing = [row["course_id"] for row in rows if row["credits"] <= 0]
    if missing:
        raise ValueError(f"课程目录缺少 {', '.join(missing)}，无法准确计算 GPA")
    return [CourseGrade(**row) for row in rows]


@tool(
    parse_docstring=True,
    description=(
        "计算本学期加权 GPA 并生成分析报告:总学分、最强/最弱课程、等级与建议。"
        "适用于「我这学期 GPA 多少」「哪门课最拉分」「绩点怎么样」。"
        "注意:这是个人敏感数据,执行前会请求用户确认。"
    ),
)
def calculate_gpa(runtime: ToolRuntime[UserContext]) -> str:
    """计算本学期加权 GPA 并生成分析报告。

    Returns:
        分析报告的 JSON 字符串(ok/total_credits/weighted_gpa/strongest/
        weakest/level/advice);无成绩数据时返回 ok=false 与 error。
    """
    user_id = (runtime.context.user_id or "").strip() if runtime.context else ""
    if not user_id:
        return _dump({"ok": False, "error": "缺少用户身份，无法读取个人成绩"})
    try:
        grades = _load_grades(user_id)
    except Exception as e:  # 第05章 §6.3(p42-43) 第 1 层防护:工具内兜住异常
        logger.error("[GPA] 读取成绩失败: %r", e)
        return _dump({"ok": False, "error": f"读取成绩数据失败:{e}"})

    if not grades:
        return _dump({"ok": False, "error": "你尚未录入本学期成绩；可在网页的个人数据中录入"})

    total = sum(g.credits for g in grades)
    gpa = round(sum(g.grade_point * g.credits for g in grades) / total, 2)
    weakest = min(grades, key=lambda g: g.grade_point)
    strongest = max(grades, key=lambda g: g.grade_point)

    if gpa >= 3.7:
        level, advice = "优秀", "保持节奏,可考虑挑战更高阶课程或参与科研/竞赛。"
    elif gpa >= 3.0:
        level, advice = (
            "良好",
            f"整体稳健。重点补 {weakest.course_id}({weakest.name},{weakest.letter}),"
            f"它是当前绩点的主要拖累项。",
        )
    else:
        level, advice = (
            "预警",
            f"绩点偏低,{weakest.course_id} 需要优先补救,"
            f"建议预约任课老师 office hour 并调整时间分配。",
        )

    report = GpaReport(
        total_credits=total,
        weighted_gpa=gpa,
        strongest=strongest,
        weakest=weakest,
        level=level,
        advice=advice,
    )

    # 工具内写长期记忆的示范(第09章 §3.3.1 p52-56 / §4.2 p74-80)。
    # store 未挂载或 context 缺失时不影响主流程,但**不静默**:
    # 第09章 §4.2(p77)的示范是 logger.error + 返回失败标志。
    _remember_latest_gpa(runtime, report)

    return _dump({"ok": True, **report.model_dump()})


def _remember_latest_gpa(runtime: ToolRuntime[UserContext], report: GpaReport) -> None:
    """把本次 GPA 结果写进长期画像(失败只记日志,不拦正事)。"""
    store = runtime.store
    if store is None or runtime.context is None:
        logger.info("[画像] 跳过 latest_gpa 写入(store 或 context 未就绪)")
        return
    user_id = (runtime.context.user_id or "").strip()
    if not user_id:
        logger.warning("[画像] 跳过 latest_gpa 写入(context.user_id 为空)")
        return
    try:
        store.put(
            ("profiles", user_id),
            "latest_gpa",
            {
                "value": (
                    f"{report.weighted_gpa}({report.level}),"
                    f"最弱 {report.weakest.course_id} {report.weakest.letter}"
                )
            },
        )
        logger.info("[画像] 写入 user=%s key=latest_gpa", user_id)
    except Exception as e:  # noqa: BLE001
        logger.error("[画像] latest_gpa 写入失败: %r", e)
