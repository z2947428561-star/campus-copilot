"""工具参数 Schema:把枚举值与范围约束交给 Pydantic 表达。

课程对应:第05章 §3.3(p20-24)+ §4.1 案例1(p26-27)

课件原话:"当工具的参数变得复杂,**需要枚举值、范围限制或更复杂的业务逻辑验证**时,
Pydantic 模型是理想的选择",并强调"每个字段的 description 参数至关重要,
直接影响大模型理解参数含义"。

为什么需要它(旧版的问题):
    旧版 8 个工具全部只靠类型注解 + docstring,且没开 parse_docstring,
    实测 convert_to_openai_tool() 的输出里 parameters.properties
    **没有任何 description**,period 只是裸 "type":"string"。
    于是模型完全不知道有哪些合法时段,只能靠 timetable.py 里
    "别传模糊词"这类中文提示,以及运行时的手工兜底。

加了 args_schema 之后实测产出(与课件 p24 的输出同型):
    "weekday": {"description": "...", "enum": [1,2,3,4,5], "type": "integer"}
    "period":  {"description": "...", "enum": ["08:30-10:00", ...], "type": "string"}
    "week_no": {"default": 1, "maximum": 14, "minimum": 1, "type": "integer"}
    非法值在函数体执行之前就抛 ValidationError(type=literal_error)。

两条落地约束(来自课件 p13-14 的"参数默认值"与 p23-24 的正例):
    1) schema 的字段名必须与函数签名一致,否则模型按 schema 传参而函数接不到;
    2) schema 的 default 必须与函数签名的默认值一致,否则不传参时行为分叉。

一个实测踩到的坑(必须记住):
    一旦给 @tool 传了 args_schema,langchain 会用 **Pydantic 模型的 docstring**
    当工具的 function.description,函数自己的 docstring 会被忽略。
    所以下面的类全部不写 docstring,改为在各个 @tool 上显式传
    description=(第05章 §3.1 p15-16:description 的优先级高于 docstring)。
"""
from typing import Literal

from pydantic import BaseModel, Field

# 时段常量:与 timetable.py 的 PERIODS 保持一致
PERIOD_VALUES = (
    "08:30-10:00",
    "10:15-11:45",
    "12:00-13:30",
    "14:00-15:30",
    "15:45-17:15",
)

# 政策文档分类:与 build_kb.py 里 front matter 的 doc_type 保持一致
DOC_TYPE_VALUES = (
    "all",
    "attendance",
    "exam",
    "academic",
    "finance",
    "scholarship",
    "visa",
    "general",
)


class EmptyClassroomInput(BaseModel):
    # 注意:此处刻意不写 docstring,避免覆盖工具自身的 description(见模块 docstring)
    weekday: Literal[1, 2, 3, 4, 5] = Field(
        description="星期几,1=周一、2=周二、3=周三、4=周四、5=周五(周末无排课数据)"
    )
    period: Literal[
        "08:30-10:00",
        "10:15-11:45",
        "12:00-13:30",
        "14:00-15:30",
        "15:45-17:15",
    ] = Field(
        description=(
            "具体的上课时段。用户说「上午」时选 10:15-11:45,"
            "说「下午」时选 14:00-15:30,不要传模糊词"
        )
    )
    week_no: int = Field(
        default=1,
        ge=1,
        le=14,
        description="目标教学周次,范围 1-14(默认第 1 周)。部分课程只在 6-14 周开课",
    )


class PolicySearchInput(BaseModel):
    query: str = Field(
        description="自然语言问题或关键词,如「补考和重修的区别」「出勤率要求」"
    )
    doc_type: str = Field(
        default="all",
        description=(
            "可选的政策分类过滤:attendance 考勤 / exam 考试 / academic 学籍成绩 / "
            "finance 费用 / scholarship 奖学金 / visa 签证 / general 通用;"
            "不确定该选哪个时留 all(检索全库)"
        ),
    )


class AcademicWeekInput(BaseModel):
    date_str: str = Field(
        default="",
        description=(
            "要查询的日期,格式 YYYY-MM-DD。留空表示查询今天。"
            "用户说「今天/明天/现在」时留空即可,系统按当天计算"
        ),
    )


class CourseQueryInput(BaseModel):
    query: str = Field(
        description="课程代码(如 CS301)或课程名关键词(如 machine learning,中英文均可)"
    )
