"""Real model plus actual callback routes, with isolated synthetic personal data only."""
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
PROFILE = ROOT / 'data/local/xmumdorm/personal-verification'
DORM = Path.home() / 'Desktop/XMUMDorm-2.0.0-LYZZ'


def main(*, cases=None, profile=PROFILE, case_check=None):
    with socket.socket() as probe:
        try: probe.bind(('127.0.0.1', 18768))
        except OSError:
            print('Test port 18768 is occupied; no process stopped.')
            return 1
    profile.mkdir(parents=True, exist_ok=True)
    secret = secrets.token_urlsafe(48)
    os.environ.update({'CAMPUS_ENV_OVERRIDE': '0', 'MEMORY_BACKEND': 'sqlite',
        'MEMORY_DB_PATH': str(profile / 'memory.db'), 'CAMPUS_AGENT_SHARED_SECRET': secret,
        'XMUMDORM_API_URL': 'http://127.0.0.1:18768', 'LANGSMITH_TRACING': 'false',
        'LLM_FALLBACK_PROVIDER': 'none', 'LLM_MAX_RETRIES': '0', 'LLM_TIMEOUT': '40', 'LLM_MAX_TOKENS': '800'})
    sys.path.insert(0, str(ROOT / 'src'))
    logging.disable(logging.CRITICAL)
    from dorm_personal import assertion as callback_assertion
    from test_dorm_integration import assertion
    from verify_dorm_live import reply_matches_history
    from fastapi.testclient import TestClient
    import config
    import server
    child = subprocess.Popen([shutil.which('node'), 'scripts/run-personal-test-app.js'], cwd=DORM,
        env={**os.environ, 'CAMPUS_AGENT_SHARED_SECRET': secret}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    report = {'passed': False, 'real_model': True, 'synthetic_personal_data': True, 'production_data_access': False, 'cases': []}
    cases = cases if cases is not None else [
        ('schedule', '7', '查我下周一的课表，列出课程、时间和教室。', 'get_my_schedule', ['Zeta', '09:15', 'TEST-B204']),
        ('todos', '7', '我有哪些未完成的待办？列出标题和截止时间。', 'get_my_todos', ['Zeta', '18:30']),
        ('other_user_empty', '8', '我有哪些未完成的待办？', 'get_my_todos', []),
        ('not_imported', '8', '查我本周的课表。', 'get_my_schedule', []),
    ]
    try:
        for attempt in range(40):
            if child.poll() is not None: raise RuntimeError('Synthetic personal callback exited')
            try:
                req = Request('http://127.0.0.1:18768/internal/campus-agent/personal/clock',
                    headers={'X-Campus-Agent-Assertion': callback_assertion('xmumdorm:7')})
                with urlopen(req, timeout=1) as response:
                    if response.status == 200: break
            except OSError: time.sleep(.15)
        else: raise RuntimeError('Synthetic callback startup timed out')
        with TestClient(server.app) as client:
            for name, user, question, expected_tool, words in cases:
                headers = {'X-Campus-Assertion': assertion(config.XMUMDORM_SHARED_SECRET, subject=user)}
                created = client.post('/internal/xmumdorm/conversations', headers=headers)
                created.raise_for_status()
                identifier = created.json()['id']
                response = client.post('/internal/xmumdorm/chat', headers=headers,
                    json={'conversation_id': identifier, 'message': question})
                events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
                answer = ''.join(event.get('text', '') for event in events if event.get('type') == 'token')
                cfg = server.conversation_config('xmumdorm:' + user, identifier)
                snapshot = server.agent_for_user('xmumdorm:' + user).get_state(cfg)
                tools = [message for message in snapshot.values.get('messages', []) if getattr(message, 'type', None) == 'tool']
                payloads = [json.loads(message.content) for message in tools if message.name == expected_tool]
                headers = {'X-Campus-Assertion': assertion(config.XMUMDORM_SHARED_SECRET, subject=user)}
                history = client.get('/internal/xmumdorm/conversations/' + identifier, headers=headers).json()
                checks = {'completed': any(event.get('type') == 'done' for event in events) and not any(event.get('type') in {'error', 'limit'} for event in events),
                    'correct_tool': bool(payloads), 'callback_succeeded': any(payload.get('status') == 'ok' for payload in payloads),
                    'expected_test_data': all(word in answer for word in words),
                    'history_matches': reply_matches_history(answer, history['messages'])}
                if user == '8': checks['no_other_user_data'] = 'Zeta' not in answer and 'TEST-B204' not in answer
                if name == 'not_imported': checks['not_imported_explained'] = '导入' in answer
                if case_check: checks.update(case_check(name, answer, payloads))
                item = {'name': name, 'answer': answer, 'checks': checks, 'passed': all(checks.values())}
                report['cases'].append(item)
                print(json.dumps({'name': name, 'passed': item['passed'], 'checks': checks}, ensure_ascii=False), flush=True)
        report['passed'] = all(item['passed'] for item in report['cases'])
    except Exception as error:
        report['error_type'] = type(error).__name__
    finally:
        child.terminate()
        try: child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill(); child.wait()
        (profile / 'check.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'passed': report['passed'], 'error_type': report.get('error_type')}, ensure_ascii=False))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
