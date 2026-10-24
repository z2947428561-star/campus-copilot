"""Real embeddings/model with synthetic guide bodies served by the actual local gateway."""
import json
import logging
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import time
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / 'data/local/xmumdorm/guide-verification'
DORM = Path.home() / 'Desktop/XMUMDorm-2.0.0-LYZZ'


def main():
    PROFILE.mkdir(parents=True, exist_ok=True)
    with socket.socket() as probe:
        try:
            probe.bind(('127.0.0.1', 18767))
        except OSError:
            print('Test port 18767 is occupied; no processes were stopped.')
            return 1
    fixtures = PROFILE / 'articles.json'
    fixtures.write_text(json.dumps([
        {'id': 101, 'title': '联调测试交通指南', 'content': '这是虚构的联调流程，不是学校实际规定。去 Zeta 测试站之前，先到蓝色机器领取编号，再去 B7 候车点。', 'category': 'campus-guide'},
        {'id': 102, 'title': '联调测试住宿指南', 'content': '这是虚构测试资料。住宿测试需要在测试接待处登记，然后领取绿色测试卡。', 'category': 'campus-guide'},
    ], ensure_ascii=False), encoding='utf-8')
    os.environ.update({'DORM_GUIDE_DB_PATH': str(PROFILE / 'guides.db'),
        'MEMORY_BACKEND': 'sqlite', 'MEMORY_DB_PATH': str(PROFILE / 'memory.db'),
        'CAMPUS_ENV_OVERRIDE': '0', 'CAMPUS_AGENT_SHARED_SECRET': secrets.token_urlsafe(48),
        'LANGSMITH_TRACING': 'false', 'LLM_FALLBACK_PROVIDER': 'none', 'LLM_MAX_RETRIES': '0',
        'LLM_TIMEOUT': '40', 'LLM_MAX_TOKENS': '600', 'MODEL_CALL_RUN_LIMIT': '4', 'TOOL_CALL_RUN_LIMIT': '4'})
    sys.path.insert(0, str(ROOT / 'src'))
    logging.disable(logging.CRITICAL)
    from guide_knowledge import sync_snapshot
    from sync_dorm_guides import fetch_snapshot
    from test_dorm_integration import assertion
    from verify_dorm_live import reply_matches_history
    from eval_dorm_answers import style_checks
    from fastapi.testclient import TestClient
    import config
    import server
    child = subprocess.Popen([shutil.which('node'), 'scripts/run-guide-export-test-app.js'], cwd=DORM,
        env={**os.environ, 'DORM_GUIDE_FIXTURE': str(fixtures)}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    report = {'passed': False, 'real_model': True, 'real_embeddings': True, 'synthetic_guides': True,
              'production_data_read_or_written': False, 'checks': {}}
    try:
        ready = False
        for _ in range(40):
            if child.poll() is not None:
                raise RuntimeError('Guide fixture exited')
            try:
                request = Request('http://127.0.0.1:18767/api/preview/health',
                    headers={'X-Preview-Token': 'local-guide-fixture-token', 'Origin': 'http://localhost:5173'})
                with urlopen(request, timeout=1) as response:
                    ready = response.status == 200
                if ready:
                    break
            except OSError:
                time.sleep(.15)
        if not ready:
            raise RuntimeError('Guide fixture startup timed out')
        snapshot = fetch_snapshot('http://127.0.0.1:18767', 'local-guide-fixture-token')
        report['index'] = sync_snapshot(snapshot)
        report['checks']['actual_gateway_exported_two_bodies'] = len(snapshot['articles']) == 2
        with TestClient(server.app) as client:
            headers = {'X-Campus-Assertion': assertion(config.XMUMDORM_SHARED_SECRET, subject='1')}
            created = client.post('/internal/xmumdorm/conversations', headers=headers)
            created.raise_for_status()
            identifier = created.json()['id']
            response = client.post('/internal/xmumdorm/chat', headers=headers,
                json={'message': '这是虚构流程的阅读测试，不是在询问学校实际要求。只按联调交通指南的测试内容回答：去 Zeta 测试站要先做什么？', 'conversation_id': identifier})
            events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
            answer = ''.join(event.get('text', '') for event in events if event.get('type') == 'token')
            state = server.agent_for_user('xmumdorm:1').get_state(server.conversation_config('xmumdorm:1', identifier))
            tools = [message for message in state.values.get('messages', []) if getattr(message, 'type', None) == 'tool']
            evidence = [item for message in tools if message.name == 'search_guides'
                        for item in json.loads(message.content).get('evidence', [])]
            headers = {'X-Campus-Assertion': assertion(config.XMUMDORM_SHARED_SECRET, subject='1')}
            history = client.get('/internal/xmumdorm/conversations/' + identifier, headers=headers).json()
            report.update(answer=answer, conversation_id=identifier)
            report['checks'].update(style_checks(answer, limit=180))
            report['checks'].update({
                'stream_completed': any(event.get('type') == 'done' for event in events) and not any(event.get('type') in {'error', 'limit'} for event in events),
                'correct_guide_tool': any(message.name == 'search_guides' for message in tools),
                'no_policy_tool': all(message.name != 'search_policy' for message in tools),
                'matched_actual_test_evidence': any(item.get('article_id') == 101 for item in evidence),
                'answered_test_fact': '蓝色机器' in answer and ('编号' in answer or '取号' in answer),
                'history_matches': reply_matches_history(answer, history['messages']),
            })
        report['passed'] = all(report['checks'].values())
    except Exception as error:
        report['error_type'] = type(error).__name__
    finally:
        child.terminate()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()
        (PROFILE / 'check.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
