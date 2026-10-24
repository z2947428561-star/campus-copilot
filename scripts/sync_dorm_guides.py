"""Synchronize published guide bodies via the read-only gateway or an offline export."""
import argparse
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from guide_knowledge import database_path, status, sync_snapshot, validate_snapshot
from check_dorm_preview_gateway import NoRedirect


def fetch_snapshot(base, token, origin='http://localhost:5173', *, opener=None):
    parsed = urlsplit(base)
    if (parsed.scheme not in {'https', 'http'} or not parsed.hostname or parsed.username or parsed.password
            or parsed.path not in {'', '/'} or parsed.query or parsed.fragment
            or (parsed.scheme == 'http' and parsed.hostname not in {'localhost', '127.0.0.1', '::1'})):
        raise ValueError('Invalid gateway origin')
    if not token or not origin:
        raise ValueError('Gateway token and local origin are required')
    opener = opener or build_opener(NoRedirect())
    after, revision, total, articles = 0, '', None, []
    for _ in range(35):
        params = {'limit': 30, 'afterId': after}
        if revision:
            params['snapshot'] = revision
        request = Request(base.rstrip('/') + '/api/preview/handbook/export?' + urlencode(params),
            headers={'X-Preview-Token': token, 'Origin': origin}, method='GET')
        try:
            with opener.open(request, timeout=30) as response:
                raw = response.read(12 * 1024 * 1024 + 1)
        except HTTPError as error:
            # Never include an HTTP response body or the request headers in an error.
            raise RuntimeError('Guide export HTTP ' + str(error.code)) from None
        if len(raw) > 12 * 1024 * 1024:
            raise ValueError('Guide export page too large')
        payload = json.loads(raw)
        if payload.get('status') != 0:
            raise ValueError('Guide export failed')
        data = payload.get('data') or {}
        current = data.get('snapshot', '')
        if data.get('schemaVersion') != 1 or not isinstance(current, str) or not re.fullmatch('[a-f0-9]{64}', current):
            raise ValueError('Unsupported guide export')
        if revision and current != revision:
            raise ValueError('Guide snapshot changed; restart synchronization')
        revision = current
        count = data.get('total')
        if type(count) is not int or not 0 <= count <= 1000 or (total is not None and count != total):
            raise ValueError('Invalid guide total')
        total = count
        items = data.get('items')
        if not isinstance(items, list) or len(items) > 30 or type(data.get('hasMore')) is not bool:
            raise ValueError('Invalid guide page')
        for row in items:
            identifier = row.get('id')
            if type(identifier) is not int or identifier <= after:
                raise ValueError('Invalid guide cursor ordering')
            after = identifier
        articles.extend(items)
        if len(articles) > total:
            raise ValueError('Guide total exceeded')
        if not data['hasMore']:
            if len(articles) != total or data.get('nextAfterId') is not None:
                raise ValueError('Incomplete guide export')
            snapshot = {'schema_version': 1, 'complete': True, 'snapshot': revision,
                        'origin': base.rstrip('/'), 'articles': articles}
            validate_snapshot(snapshot)
            return snapshot
        if not items or data.get('nextAfterId') != after:
            raise ValueError('Non-advancing guide cursor')
    raise ValueError('Guide export page limit exceeded')


def save_snapshot(snapshot, path):
    """Only the validated, complete public-content export is saved; no credentials."""
    allowed = {'id', 'title', 'summary', 'content', 'contentType', 'externalUrl', 'category', 'status', 'publishedAt', 'updatedAt',
               'source_type', 'sourceUrl', 'collectedAt', 'sourceUpdatedAt'}
    clean = {key: snapshot[key] for key in ('schema_version', 'complete', 'snapshot', 'origin', 'fixture') if key in snapshot}
    clean['articles'] = [{key: value for key, value in row.items() if key in allowed} for row in snapshot['articles']]
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(clean, stream, ensure_ascii=False, indent=2)
        temporary.replace(path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--from-json', type=Path, help='Import a complete, published-only offline snapshot')
    parser.add_argument('--env-file', type=Path, help='Read only PREVIEW_GATEWAY_* keys from an existing local env file')
    parser.add_argument('--db', type=Path, default=database_path())
    parser.add_argument('--snapshot-file', type=Path, default=ROOT / 'data/local/xmumdorm/guides-snapshot.json')
    parser.add_argument('--export-only', action='store_true', help='Save a complete snapshot without calling embeddings')
    parser.add_argument('--status', action='store_true')
    args = parser.parse_args()
    indexed = False
    try:
        if args.status:
            print(json.dumps(status(args.db), ensure_ascii=False))
            return 0
        previous = status(args.db)['revision']
        if args.from_json:
            if args.from_json.stat().st_size > 12 * 1024 * 1024:
                raise ValueError('Offline guide snapshot too large')
            snapshot = json.loads(args.from_json.read_text(encoding='utf-8-sig'))
            if snapshot.get('fixture') and args.db.resolve() == database_path():
                raise ValueError('Test snapshots require an explicit separate --db path')
        else:
            settings = {}
            if args.env_file:
                from dotenv import dotenv_values
                settings = dotenv_values(args.env_file)
            snapshot = fetch_snapshot(
                os.environ.get('PREVIEW_GATEWAY_URL') or settings.get('PREVIEW_GATEWAY_URL', ''),
                os.environ.get('PREVIEW_GATEWAY_TOKEN') or settings.get('PREVIEW_GATEWAY_TOKEN', ''),
                os.environ.get('PREVIEW_GATEWAY_ORIGIN') or settings.get('PREVIEW_GATEWAY_ORIGIN', 'http://localhost:5173'))
        validate_snapshot(snapshot)
        if args.export_only:
            result = {'articles': len(snapshot['articles']), 'indexed': False}
        else:
            result = {**sync_snapshot(snapshot, path=args.db, expected_revision=previous), 'indexed': True}
            indexed = True
        save_snapshot(snapshot, args.snapshot_file)
        print(json.dumps({'ok': True, **result}, ensure_ascii=False))
        return 0
    except Exception as error:
        # Only our controlled HTTP error can be printed; third-party errors may contain secrets.
        detail = str(error) if type(error) is RuntimeError and re.fullmatch('Guide export HTTP [0-9]{3}', str(error)) else type(error).__name__
        print(json.dumps({'ok': False, 'error': detail, 'index_updated': indexed}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
