"""Format completed Dorm answers without attribution prefixes or unasked fields."""
import re


ATTRIBUTION = re.compile(
    r'^\s*(?P<prefix>(?:来自|根据|依据|按照|按)[^，,。：:\n]{0,60}'
    r'(?:资料|手册|指南|知识库|快照)[^，,。：:\n]{0,20})[，,:：]\s*'
)


def format_answer(text, question=None):
    match = ATTRIBUTION.match(text)
    body = text
    if match:
        body = text[match.end():]
        # Preserve an audience condition even when it appeared in a handbook title.
        audience = re.search(r'SFS\s*(?:学生)?|本科生|研究生', match['prefix'], re.I)
        if audience and audience.group() not in body:
            body = audience.group() + '：' + body
    if not question:
        return body
    if (re.search(r'哪套(?:账号|账户)|(?:哪|什么).*?(?:账号|账户)', question)
            and not re.search(r'密码|同步|重置|改密', question)):
        # Keep account identifiers, including passport/IC when those ARE the login
        # identifier. Remove only clauses explicitly about unasked password details.
        sentences = []
        for sentence in re.split(r'[。\n]', body):
            clauses = [clause.strip() for clause in re.split(r'[，,；;]', sentence)
                       if clause.strip() and not re.search(r'密码|改密|重置|同步', clause)]
            if clauses:
                sentences.append('，'.join(clauses).rstrip('，,；;'))
        if sentences:
            body = '。'.join(sentences) + '。'
    return body
