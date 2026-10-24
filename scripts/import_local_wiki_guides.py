"""Import existing complete public Wiki snapshots; never connect to the Wiki or a proxy."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from guide_knowledge import database_path, status, sync_snapshot
from sync_dorm_guides import save_snapshot

BASE = 'https://surivivexmum.wiki'
CATEGORIES = {'入学篇', '生活篇', '学习篇'}


def prepare(folder):
    state = json.loads((folder / 'snapshot.json').read_text(encoding='utf-8'))
    manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
    rows = [json.loads(line) for line in (folder / 'pages.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    public = {page['path']: page for page in manifest['pages'] if not page.get('draft')}
    if (state.get('status') != 'complete' or state.get('saved') != len(rows) or state.get('selected') != len(rows)
            or len(rows) != len(public) or {row['path'] for row in rows} != set(public)):
        raise ValueError('A complete unfiltered public snapshot is required')
    articles, skipped = [], []
    for row in sorted(rows, key=lambda row: row['path']):
        path, content = row['path'], row['content']
        if row['category'] != public[path].get('category', '') or row.get('source_type') != 'student_wiki':
            raise ValueError('Wiki metadata mismatch')
        if hashlib.sha256(content.encode('utf-8')).hexdigest() != row['sha256']:
            raise ValueError('Wiki body hash mismatch')
        source = BASE + '/docs/' + quote(path, safe='/')
        if row['source_url'] != source:
            raise ValueError('Wiki source URL mismatch')
        if row['category'] not in CATEGORIES:
            skipped.append({'path': path, 'reason': 'outside_core_guide_categories'})
            continue
        # Keep substantive paragraphs on partly unfinished pages; do not index boilerplate.
        clean = re.sub(r'(?m)^.*本页内容待完善.*(?:\n|$)', '', content).strip()
        visible = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', clean)
        visible = re.sub(r'(?m)^\s*#{1,6}\s+.*$', '', visible)
        visible = re.sub(r'<[^>]+>', '', visible)
        if len(re.sub(r'\W', '', visible)) < 40:
            skipped.append({'path': path, 'reason': 'empty_placeholder_or_image_only'})
            continue
        articles.append({'id': 10**12 + int(hashlib.sha256(path.encode()).hexdigest()[:10], 16),
            'status': 'published', 'title': row['title'], 'category': row['category'],
            'contentType': 'markdown', 'content': clean, 'source_type': 'student_wiki', 'sourceUrl': source,
            'collectedAt': row.get('fetched_at') or '', 'sourceUpdatedAt': row.get('lastUpdated') or ''})
    if not articles:
        raise ValueError('No substantive core guides in this snapshot')
    snapshot = {'schema_version': 1, 'complete': True, 'origin': BASE, 'articles': articles}
    report = {'snapshot_folder': str(folder), 'downloaded_pages': len(rows), 'selected_categories': sorted(CATEGORIES),
              'imported_articles': len(articles), 'skipped': skipped,
              'wiki_network_requests': 0, 'production_database_access': False}
    return snapshot, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot-dir', type=Path, required=True)
    parser.add_argument('--db', type=Path, default=database_path())
    parser.add_argument('--prepare-only', action='store_true')
    args = parser.parse_args()
    target = ROOT / 'data/local/xmumdorm'
    try:
        previous = status(args.db)['revision']
        snapshot, report = prepare(args.snapshot_dir)
        if not args.prepare_only:
            report['index'] = sync_snapshot(snapshot, path=args.db, expected_revision=previous)
        save_snapshot(snapshot, target / 'guides-snapshot.json')
        (target / 'wiki-import.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({key: value for key, value in report.items() if key != 'skipped'}, ensure_ascii=False))
        return 0
    except Exception as error:
        print(json.dumps({'ok': False, 'error_type': type(error).__name__}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
