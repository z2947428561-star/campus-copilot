"""Dorm community guides are deliberately separate from official policy evidence."""
import json
import logging
from langchain_core.tools import tool


@tool(description='检索 XMUMDorm 社区指南：新生报到、住宿、校园生活、交通、学校网站和账号使用、周边经验。不能用作校方教务政策依据；政策问题用 search_policy。')
def search_guides(query: str) -> str:
    """Search only the imported published community-guide snapshot."""
    if not isinstance(query, str) or not 2 <= len(query.strip()) <= 300:
        return json.dumps({'status': 'insufficient_evidence', 'evidence': []})
    try:
        from guide_knowledge import search
        return json.dumps(search(query.strip()), ensure_ascii=False)
    except Exception as error:
        logging.getLogger('campus').warning('[指南检索] %s', type(error).__name__)
        return json.dumps({'status': 'unavailable', 'reason': 'guide_retrieval_unavailable', 'evidence': []})
