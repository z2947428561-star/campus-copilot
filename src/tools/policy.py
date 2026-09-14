"""教务政策检索工具(占位版)。

M5 将升级为 Milvus 向量检索(带来源引用);当前做两件事:
1. data/raw_docs 有文档时按文件名关键词匹配(文档丢进去立刻可用)
2. 没有文档时诚实说明未接入 —— 绝不编造政策

对应验收场景:"补考和重修有什么区别""奖学金怎么评"
"""
from pathlib import Path

from langchain_core.tools import tool

RAW_DOCS = Path("data/raw_docs")


@tool
def search_policy(keyword: str) -> str:
    """检索教务政策文档(补考、重修、奖学金、学籍等)。

    注意:本工具当前为占位版,知识库建设中(M5 接入完整向量检索)。
    若返回"无法给出权威答案",请如实告知用户,不要自行编造政策内容。

    Args:
        keyword: 检索关键词,如 "补考" "resit" "重修" "奖学金" "scholarship"
    """
    docs = [p for p in RAW_DOCS.rglob("*") if p.is_file() and not p.name.startswith(".")]

    if not docs:
        return (
            "教务政策知识库尚未建立(将于 M5 接入学校公开教务文档)。"
            "当前无法给出政策类问题的权威答案,建议用户查阅学校官网 "
            "www.xmu.edu.my 或教务处/学生事务处通知。"
        )

    kw = keyword.lower()
    matched = [p.name for p in docs if kw in p.name.lower()]
    if matched:
        return (
            f"找到 {len(matched)} 份相关文档:{', '.join(matched)}。"
            f"注意:全文内容检索将于 M5 上线,当前仅按文件名匹配,建议用户打开原文核实。"
        )
    return (
        f"知识库现有 {len(docs)} 份文档,未匹配到与「{keyword}」相关的文件。"
        f"全文检索将于 M5 上线,建议用户查阅学校官网 www.xmu.edu.my。"
    )
