"""Own-account read tools; no model-supplied identity, token or URL parameters."""
import json
from typing import Annotated, Any, Literal
from pydantic import BaseModel, ConfigDict, Field
from langchain_core.tools import InjectedToolArg, tool
from langgraph.prebuilt import ToolRuntime
from context import UserContext
from dorm_personal import read_personal


class ScheduleInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    # ToolNode supplies this field; InjectedToolArg keeps it out of model input.
    runtime: Annotated[Any, InjectedToolArg] = None
    when: Literal['today', 'tomorrow', 'this_week', 'next_week', 'date', 'week'] = Field(default='today', description='今天、明天、本周、下周、指定日期或指定教学周；相对日期由网站按学校时区计算')
    date: str = Field(default='', max_length=10, description='仅 when=date 时填写 YYYY-MM-DD')
    week: int = Field(default=0, ge=0, le=60, description='仅 when=week 时填写教学周，不能用第1周代替当前周')
    weekday: int = Field(default=0, ge=0, le=7, description='周查询可指定周几：1周一至7周日；0为整周。今天、明天、指定日期时不填写')


class TodoInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    runtime: Annotated[Any, InjectedToolArg] = None
    when: Literal['all', 'today', 'tomorrow', 'date', 'overdue'] = Field(default='all', description='全部日期、今天到期、明天到期、指定截止日期或已逾期；日期筛选不含未设日期的事项')
    status: Literal['active', 'completed', 'all'] = Field(default='active', description='未完成、已完成或所有状态；默认未完成')
    date: str = Field(default='', max_length=10, description='仅 when=date 时填写 YYYY-MM-DD')
    page: int = Field(default=1, ge=1, le=100, description='每页20条；hasMore=true 时可查询下一页')


class HolidayInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    runtime: Annotated[Any, InjectedToolArg] = None
    when: Literal['next', 'upcoming', 'this_semester', 'this_year', 'year', 'today', 'tomorrow', 'date', 'range'] = Field(default='upcoming', description='下一次、之后已收录、本学期、今年、指定年、今天、明天、指定日或日期范围')
    year: int = Field(default=0, ge=0, le=2100, description='仅 when=year 时填四位年份')
    name: str = Field(default='', max_length=80, description='可按节日中英文名称筛选，例如圣诞节、Deepavali')
    date: str = Field(default='', max_length=10, description='仅 when=date 时填 YYYY-MM-DD')
    start: str = Field(default='', max_length=10, description='仅 when=range 时填开始日期 YYYY-MM-DD')
    end: str = Field(default='', max_length=10, description='仅 when=range 时填结束日期 YYYY-MM-DD')


@tool(args_schema=HolidayInput, description='读取网站“放假日”模块的共享公共假期，查询下次放假、距今几天、本学期/今年/指定年份的节日、某节日日期或某天是否收录假期。日期倒计时由网站按学校时区计算；不是个人课表，也不提供寒暑假或调课信息。')
def get_campus_holidays(when: str = 'upcoming', year: int = 0, name: str = '', date: str = '', start: str = '', end: str = '',
                        runtime: ToolRuntime[UserContext] = None) -> str:
    """Query the existing Holidays module without changing records."""
    params = {'when': when}
    for key, value in {'year': year, 'name': name, 'date': date, 'start': start, 'end': end}.items():
        if value: params[key] = value
    return json.dumps(read_personal('holidays', params, runtime), ensure_ascii=False)


@tool(args_schema=ScheduleInput, description='查询当前登录账号最近导入的网站个人课表，支持今天/明天/本周/下周/指定日期和教学周，返回时间、课程、教室、教师。不是全校课表，不读取其他用户，不是官方实时教务排课。')
def get_my_schedule(when: str = 'today', date: str = '', week: int = 0, weekday: int = 0,
                    runtime: ToolRuntime[UserContext] = None) -> str:
    """Read the authenticated user's actual imported timetable."""
    params = {'when': when}
    if date: params['date'] = date
    if week: params['week'] = week
    if weekday: params['weekday'] = weekday
    return json.dumps(read_personal('schedule', params, runtime), ensure_ascii=False)


@tool(args_schema=TodoInput, description='只读查询当前登录账号的网站待办，支持未完成/已完成、全部日期/今天/明天/指定日期/逾期及分页；不新增、删除、修改或完成待办。')
def get_my_todos(when: str = 'all', status: str = 'active', date: str = '', page: int = 1,
                 runtime: ToolRuntime[UserContext] = None) -> str:
    """Read only the authenticated user's todo titles, priorities and deadlines."""
    params = {'when': when, 'status': status, 'page': page}
    if date: params['date'] = date
    return json.dumps(read_personal('todos', params, runtime), ensure_ascii=False)


@tool(description='读取网站当前的学校时区日期、星期、当前教学周和学期范围。今天/明天/本周等以此为准，不使用演示校历。')
def get_my_campus_clock(runtime: ToolRuntime[UserContext]) -> str:
    """Return the school's live calendar context for the logged-in user."""
    return json.dumps(read_personal('clock', {}, runtime), ensure_ascii=False)
