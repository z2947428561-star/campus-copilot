"""提示词模板库(第04章 §2.4.3 p40-41)。

按课件的建议把提示词集中管理,业务代码不再各写一份字符串:

    prompts/
        __init__.py    统一出口
        common.py      人设 / 风格 / 诚实底线 / 收口
        discipline.py  工具纪律 / 记忆纪律 / 引用纪律
        system.py      按运行阶段组装

为什么不再用 src/prompt.py 里那份独立人设:
    那份写的是"你目前只能做通用问答,还无法查询具体学校的课表、政策等真实数据",
    与 Agent 版要求的"必须先调 search_policy 检索原文"直接矛盾 ——
    同一产品的两个入口给了相反的能力口径。
    现在只保留一份文案,从本包导出。
"""
from prompts.common import CLOSING, HONESTY, PERSONA, STYLE
from prompts.discipline import CITATION_DISCIPLINE, MEMORY_DISCIPLINE, TOOL_DISCIPLINE
from prompts.system import FIXED_VARS, build_prompt, build_system_prompt

__all__ = [
    "PERSONA",
    "STYLE",
    "HONESTY",
    "CLOSING",
    "TOOL_DISCIPLINE",
    "MEMORY_DISCIPLINE",
    "CITATION_DISCIPLINE",
    "FIXED_VARS",
    "build_prompt",
    "build_system_prompt",
]
