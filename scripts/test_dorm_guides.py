"""Guide import, withdrawal, isolation and bounded read-only transport checks."""
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

os.environ['CAMPUS_SKIP_DOTENV'] = '1'
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import config
import guide_knowledge as guides
from sync_dorm_guides import fetch_snapshot, save_snapshot


class Vectors:
    def __init__(self):
        self.calls = 0

    def embed_documents(self, texts):
        self.calls += 1
        return [self.embed_query(text) for text in texts]

    def embed_query(self, text):
        return [1., 0., 0.] if '住宿' in text else [0., 1., 0.] if '交通' in text else [0., 0., 1.]


def article(identifier=1, **fields):
    return {'id': identifier, 'status': 'published', 'title': '住宿指南', 'content': '住宿测试：到测试接待点办理。',
            'category': 'campus-guide', 'contentType': 'markdown', **fields}


def snapshot(*articles):
    return {'schema_version': 1, 'complete': True, 'origin': 'https://dorm.example', 'articles': list(articles)}


class GuideTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'guides.db'
        self.model = Vectors()
        self.dimension = patch.object(config, 'EMBED_DIM', 3)
        self.dimension.start()

    def tearDown(self):
        self.dimension.stop()
        self.tmp.cleanup()

    def sync(self, data, **kwargs):
        return guides.sync_snapshot(data, path=self.path, embeddings=self.model, **kwargs)

    def test_import_reuses_vectors_and_retrieves_only_relevant_guides(self):
        data = snapshot(article(), article(2, title='交通指南', content='交通测试：乘坐测试车辆。'))
        self.sync(data)
        self.sync(data)
        self.assertEqual(self.model.calls, 1)
        hits = guides.search('住宿怎么办', path=self.path, embeddings=self.model)
        self.assertEqual([item['article_id'] for item in hits['evidence']], [1])
        self.assertEqual(hits['evidence'][0]['source_type'], 'community_guide')
        self.assertEqual(guides.search('火星天气', path=self.path, embeddings=self.model)['evidence'], [])

    def test_complete_replacement_removes_withdrawn_articles(self):
        self.sync(snapshot(article(), article(2, title='交通指南', content='交通测试')))
        self.sync(snapshot(article(2, title='交通指南', content='交通测试')))
        self.assertEqual(guides.search('住宿', path=self.path, embeddings=self.model)['evidence'], [])
        self.sync(snapshot())
        self.assertEqual(guides.status(self.path)['chunks'], 0)

    def test_rejects_drafts_duplicates_and_incomplete_snapshots_without_losing_old(self):
        self.sync(snapshot(article()))
        for data in [snapshot(article(status='draft')), snapshot(article(), article()),
                     {**snapshot(), 'complete': False}, snapshot(article(contentType='html'))]:
            with self.assertRaises(ValueError):
                self.sync(data)
        self.assertEqual(guides.status(self.path)['revision'], 1)

    def test_embedding_failure_and_concurrent_publication_preserve_old(self):
        self.sync(snapshot(article()))
        with patch.object(self.model, 'embed_documents', side_effect=RuntimeError('synthetic failure')):
            with self.assertRaises(RuntimeError):
                self.sync(snapshot(article(content='住宿新内容')))
        with self.assertRaises(ValueError):
            self.sync(snapshot(), expected_revision=0)
        self.assertEqual(guides.status(self.path)['articles'], 1)
        self.assertEqual(guides.status(self.path)['revision'], 1)

    def test_external_links_index_only_summary_and_policy_gate_stays_strict(self):
        self.sync(snapshot(article(contentType='external_link', summary='住宿摘要', content='不应读到的外部正文')))
        hit = guides.search('住宿', path=self.path, embeddings=self.model)['evidence'][0]
        self.assertEqual(hit['text'], '住宿摘要')
        from langchain_core.documents import Document
        from policy_evidence import rejection_reason
        self.assertEqual(rejection_reason(Document(page_content=hit['text'], metadata=hit), .99, .7), 'unknown_or_non_policy_source')

    def test_missing_or_wrong_embedding_index_is_unavailable(self):
        self.assertEqual(guides.search('住宿', path=self.path)['reason'], 'guides_not_imported')
        self.sync(snapshot(article()))
        with patch.object(guides, 'embedding_contract', return_value='changed'):
            self.assertEqual(guides.search('住宿', path=self.path)['reason'], 'guide_index_needs_sync')

    def test_transport_pagination_and_snapshot_consistency(self):
        requests = []
        revision = 'a' * 64
        class Opener:
            def open(inner, request, timeout):
                requests.append(request)
                second = len(requests) == 2
                payload = {'status': 0, 'data': {'schemaVersion': 1, 'snapshot': revision, 'total': 2,
                    'items': [article(2 if second else 1)], 'hasMore': not second, 'nextAfterId': None if second else 1}}
                return io.BytesIO(json.dumps(payload).encode())
        result = fetch_snapshot('https://dorm.example', 'test-only-token', opener=Opener())
        self.assertEqual(len(result['articles']), 2)
        query = parse_qs(urlsplit(requests[1].full_url).query)
        self.assertEqual(query['snapshot'], [revision])
        self.assertNotIn('test-only-token', requests[1].full_url)
        self.assertEqual(requests[1].get_header('X-preview-token'), 'test-only-token')

    def test_incomplete_http_export_cannot_replace_existing_snapshot(self):
        class Broken:
            def open(inner, request, timeout):
                return io.BytesIO(json.dumps({'status': 0, 'data': {'schemaVersion': 1, 'snapshot': 'a' * 64,
                    'total': 2, 'items': [article()], 'hasMore': False, 'nextAfterId': None}}).encode())
        with self.assertRaises(ValueError):
            fetch_snapshot('https://dorm.example', 'test', opener=Broken())

    def test_changed_or_stalled_page_is_rejected(self):
        for changed, stalled in [(True, False), (False, True)]:
            class Pages:
                calls = 0

                def open(inner, request, timeout):
                    inner.calls += 1
                    second = inner.calls == 2
                    data = {'schemaVersion': 1, 'snapshot': ('b' if second and changed else 'a') * 64,
                        'total': 2, 'items': [article(1 if stalled or not second else 2)],
                        'hasMore': not second, 'nextAfterId': 1 if not second else None}
                    return io.BytesIO(json.dumps({'status': 0, 'data': data}).encode())
            with self.assertRaises(ValueError):
                fetch_snapshot('https://dorm.example', 'test', opener=Pages())

    def test_snapshot_file_drops_account_fields(self):
        target = Path(self.tmp.name) / 'export.json'
        save_snapshot(snapshot(article(email='private@example.test', authorInfo={'id': 99})), target)
        self.assertNotIn('private@example', target.read_text(encoding='utf-8'))
        self.assertNotIn('authorInfo', target.read_text(encoding='utf-8'))

    def test_dorm_stream_and_history_hide_internal_tool_narration(self):
        from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
        from agent.streaming import stream_turn
        from chat_history import _rows
        planning = AIMessage(content='我先检索一下。', id='plan', tool_calls=[
            {'id': 'call', 'name': 'search_guides', 'args': {'query': '住宿'}}])
        final = AIMessage(content='先到接待处登记。', id='answer')
        class Graph:
            def stream(inner, *args, **kwargs):
                yield 'messages', (AIMessageChunk(content=planning.content), {'langgraph_node': 'model'})
                yield 'updates', {'model': {'messages': [planning]}}
                yield 'updates', {'tools': {'messages': [ToolMessage('资料', tool_call_id='call')]}}
                yield 'messages', (AIMessageChunk(content=final.content), {'langgraph_node': 'model'})
                yield 'updates', {'model': {'messages': [final]}}
        chunks = []
        reply = stream_turn(Graph(), {}, {}, lambda _: None, on_token=chunks.append, final_answers_only=True)
        self.assertEqual(reply, final.content)
        self.assertEqual(chunks, [final.content])
        self.assertEqual([row[2] for row in _rows([planning, final], None, hide_tool_narration=True)], [final.content])
        self.assertEqual([row[2] for row in _rows([planning, final], None)], [planning.content, final.content])
        self.assertEqual(stream_turn(Graph(), {}, {}, lambda _: None), planning.content + final.content)

    def test_attribution_cleanup_preserves_conditions_and_matches_saved_text(self):
        from dorm_answer import format_answer
        from chat_history import _rows
        from langchain_core.messages import AIMessage
        self.assertEqual(format_answer('按该测试指南的内容，先到接待处登记。'), '先到接待处登记。')
        self.assertEqual(format_answer('来自新生指南：如果已经预约，可直接登记。'), '如果已经预约，可直接登记。')
        self.assertEqual(format_answer('根据本科生手册，满足条件才能申请。'), '本科生：满足条件才能申请。')
        self.assertEqual(format_answer('按预约时间到场。'), '按预约时间到场。')
        raw = '根据交通指南，先预约。'
        self.assertEqual(_rows([AIMessage(content=raw)], None, hide_tool_narration=True)[0][2], format_answer(raw))

    def test_account_scope_preserves_useful_facility_details(self):
        from dorm_answer import format_answer
        from chat_history import _rows
        from langchain_core.messages import AIMessage
        account = 'Moodle 和 AC 都用 Campus ID：账号是学号，初始密码一般为护照后六位。这两个系统的密码同步。'
        question = 'Moodle 和 AC 用哪套账号？'
        self.assertEqual(format_answer(account, question), 'Moodle 和 AC 都用 Campus ID：账号是学号。')
        self.assertEqual(format_answer(account, '账号和密码分别是什么？'), account)
        self.assertIn('护照号', format_answer('国际学生的账号是护照号，密码需自行设置。', '国际学生用什么账号？'))
        gym = '健身房在 B1 综合楼 3 楼，开放时间是 8:00–22:00。'
        self.assertEqual(format_answer(gym, '健身房在哪栋楼？'), gym)
        preferred = '健身房在 B1 综合楼 3 楼，分无氧和有氧两个区域，开放时间为周一至周日 8:00–22:00。'
        self.assertEqual(format_answer(preferred, '学校的健身房在哪栋楼？'), preferred)
        self.assertEqual(format_answer(gym, '健身房在哪栋楼、几层、几点开放？'), gym)
        self.assertEqual(format_answer('健身房在 B1 楼后面的小楼。', '健身房在哪栋楼？'), '健身房在 B1 楼后面的小楼。')
        self.assertEqual(_rows([AIMessage(content=account)], None, hide_tool_narration=True, question=question)[0][2], format_answer(account, question))

    def test_wiki_provenance_is_preserved_and_cannot_impersonate_policy(self):
        row = article(source_type='student_wiki', sourceUrl='https://dorm.example/docs/campus',
                      collectedAt='2026-10-03T00:00:00Z')
        self.sync(snapshot(row))
        hit = guides.search('住宿', path=self.path, embeddings=self.model)['evidence'][0]
        self.assertEqual(hit['source'], row['sourceUrl'])
        self.assertEqual(hit['source_type'], 'student_wiki')
        self.assertEqual(hit['collected_at'], row['collectedAt'])
        from langchain_core.documents import Document
        from policy_evidence import rejection_reason
        self.assertEqual(rejection_reason(Document(page_content=hit['text'], metadata=hit), .99, .7), 'unknown_or_non_policy_source')
        with self.assertRaises(ValueError):
            self.sync(snapshot({**row, 'sourceUrl': 'https://elsewhere.example/docs/campus'}))

    def test_wiki_conversion_checks_hashes_and_skips_placeholders(self):
        import hashlib
        from urllib.parse import quote
        from import_local_wiki_guides import prepare
        folder = Path(self.tmp.name) / 'wiki'
        folder.mkdir()
        pages = [{'path': '生活篇/测试正文', 'category': '生活篇'}, {'path': '生活篇/空白', 'category': '生活篇'}]
        records = []
        for page in pages:
            content = ('住宿登记流程的真实正文测试。' * 8) if page['path'].endswith('测试正文') else '## 暂无内容'
            records.append({**page, 'title': page['path'], 'content': content, 'source_type': 'student_wiki',
                'source_url': 'https://surivivexmum.wiki/docs/' + quote(page['path'], safe='/'),
                'sha256': hashlib.sha256(content.encode()).hexdigest()})
        (folder / 'manifest.json').write_text(json.dumps({'pages': pages}), encoding='utf-8')
        (folder / 'snapshot.json').write_text(json.dumps({'status': 'complete', 'selected': 2, 'saved': 2}), encoding='utf-8')
        def write_rows():
            (folder / 'pages.jsonl').write_text('\n'.join(json.dumps(row) for row in records), encoding='utf-8')
        write_rows()
        converted, report = prepare(folder)
        self.assertEqual(len(converted['articles']), 1)
        self.assertEqual(converted['articles'][0]['sourceUrl'], records[0]['source_url'])
        self.assertEqual(report['skipped'][0]['reason'], 'empty_placeholder_or_image_only')
        records[0]['content'] += 'tamper'
        write_rows()
        with self.assertRaises(ValueError):
            prepare(folder)


if __name__ == '__main__':
    unittest.main()
