"""Bounded context collection. API payloads are projected to text; metrics are discarded."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

from .common import atomic_write, canonical, read_json


def project(payload, post_id):
    status = payload.get('status') or {}
    if payload.get('code') != 200 or status.get('type') != 'status' or status.get('id') != post_id:
        return {'state': 'unavailable', 'post_id': post_id, 'code': payload.get('code'), 'text': None}
    return {'state': 'available', 'post_id': post_id, 'text': status.get('text', ''),
            'post_url': status.get('url'), 'created_at': status.get('created_at'),
            'author_handle': (status.get('author') or {}).get('screen_name'),
            'note': 'Current focal post only. Quotes/replies, profile, engagement metrics excluded.'}


def fetch_child(pid):
    url = 'https://api.fxtwitter.com/2/status/' + pid
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'illustration-research/2'})
        with urllib.request.urlopen(req, timeout=8) as response:
            payload = response.read(2 * 1024 * 1024 + 1)
            if len(payload) > 2 * 1024 * 1024:
                raise ValueError('payload too large')
            result = project(json.loads(payload), pid)
    except urllib.error.HTTPError as e:
        result = {'state': 'technical_failure', 'code': e.code, 'text': None}
    except Exception as e:
        result = {'state': 'technical_failure', 'error': type(e).__name__, 'text': None}
    result.update(post_id=pid, retrieved_at=datetime.now(timezone.utc).isoformat(), source_url=url)
    print(json.dumps(result, ensure_ascii=True))


def fetch(pid, path):
    assert re.fullmatch(r'\d{2,20}', pid)
    path = Path(path)
    if path.exists():
        cached = read_json(path)
        if cached.get('post_id') != pid:
            raise ValueError('Context cache belongs to another post; use the per-post worker path')
        return cached
    start = time.monotonic()
    try:
        child = subprocess.run([sys.executable, '-m', 'pipeline_v4.context', '_fetch', pid],
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=12, check=True)
        result = json.loads(child.stdout)
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, ValueError):
        result = {'state': 'technical_failure', 'error': 'request_failed_or_12s_timeout', 'text': None,
                  'retrieved_at': datetime.now(timezone.utc).isoformat()}
    result.update(post_id=pid, elapsed_seconds=round(time.monotonic() - start, 3))
    atomic_write(path, canonical(result))
    return result


def budget(path, action, clock=time.time, query=None):
    if action not in {'budget','search','page'}:
        raise ValueError('Unknown context budget action')
    path = Path(path)
    now = clock()
    state = read_json(path) if path.exists() else {'started_at': now, 'deadline': now + 60, 'searches': 0, 'pages': 0,'queries':[]}
    if action=='search' and (not isinstance(query,str) or not query.strip() or len(query)>500):
        raise ValueError('One actual query text is required for each reserved search')
    key = {'search': 'searches', 'page': 'pages'}.get(action)
    permitted = now < state['deadline'] and (key is None or state[key] < {'searches': 2, 'pages': 3}[key])
    if permitted and key:
        state[key] += 1
        if action=='search':state['queries'].append({'query':query,'reserved_at':now})
    atomic_write(path, canonical(state))
    return dict(state, permitted=permitted, remaining_seconds=max(0, state['deadline'] - now))


def report(path, clock=time.time):
    """No new ledger or network request; safe to call after ending the search."""
    path = Path(path)
    if not path.exists():
        return {'searches': 0, 'pages': 0, 'elapsed_seconds': 0}
    state = read_json(path)
    return {'searches':state['searches'], 'pages':state['pages'],
            'elapsed_seconds':round(max(0,clock()-state['started_at']),3)}


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('command', choices=['fetch', '_fetch', 'budget', 'search', 'page'])
    p.add_argument('target', help='post ID for fetch; ledger path for budget/search/page')
    p.add_argument('--output')
    a = p.parse_args()
    if a.command == '_fetch':
        fetch_child(a.target)
    elif a.command == 'fetch':
        print(json.dumps(fetch(a.target, a.output or '.runtime/context/' + a.target + '.json'), ensure_ascii=True))
    else:
        print(json.dumps(budget(a.target, a.command)))
