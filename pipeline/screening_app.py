"""Browse the full corpus locally; only the human selects exclusions."""
import argparse
from functools import lru_cache
import hashlib
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import re
import secrets
import sqlite3
from urllib.parse import parse_qs, urlsplit
from urllib.request import urlopen
import webbrowser
import zipfile

from .common import canonical
from .review_app import Handler as LocalHandler
from .screening import ROOT, ScreeningStore, build_index
from .human_source import bundle_root


class ScreeningServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 64

    def __init__(self, address, index, db_path, bundle_root, web_root=None):
        super().__init__(address, Handler)
        self.index, self.bundle_root = index, Path(bundle_root)
        self.web_root = Path(web_root or ROOT / 'screening_app')
        self.store = ScreeningStore(db_path, index)
        self.token = secrets.token_urlsafe(32)
        self.images = {}
        for p in index['posts']:
            for im in p['images']:
                self.images.setdefault(im['sha256'], (p['asset'], im['path']))

    @lru_cache(maxsize=32)
    def image(self, sha):
        asset, path = self.images[sha]
        with zipfile.ZipFile(self.bundle_root / asset) as z:
            data = z.read(path)
        if hashlib.sha256(data).hexdigest() != sha:
            raise ValueError('Image checksum mismatch')
        return data


def summary(snapshot):
    return {k: v for k, v in snapshot.items() if k not in {'decisions','effective_excluded_ids','excluded_image_sha256'}}


class Handler(LocalHandler):
    def do_GET(self):
        if not self.local_host():
            return self.send_json(403, {'error': 'Local access only'})
        parsed = urlsplit(self.path)
        path = parsed.path
        if path == '/api/health':
            return self.send_json(200, {'app': 'illustration-human-screening', 'total_posts': self.server.index['total_posts']})
        if path == '/api/summary':
            return self.send_json(200, dict(summary(self.server.store.snapshot()), token=self.server.token))
        if path == '/api/export':
            return self.send_bytes(200, canonical(self.server.store.export()), extra={'Content-Disposition':'attachment; filename="screening-decisions.json"'})
        if path == '/api/page':
            query = parse_qs(parsed.query)
            try:
                page = max(1, int(query.get('page', ['1'])[0]))
                size = int(query.get('size', ['48'])[0])
                if size not in {24, 48, 96}:
                    raise ValueError()
            except ValueError:
                return self.send_json(400, {'error': 'Invalid page size'})
            snapshot = self.server.store.snapshot()
            effective = set(snapshot['effective_excluded_ids'])
            choice, search = query.get('filter', ['all'])[0], query.get('q', [''])[0].strip()
            selected = []
            for p in self.server.index['posts']:
                decision = snapshot['decisions'].get(p['post_id'], {}).get('decision', 'pending')
                linked = p['post_id'] in effective and decision != 'exclude'
                state = 'linked_exclude' if linked else decision
                if choice == 'old_excluded':
                    if not p['previously_excluded']:
                        continue
                elif choice != 'all' and state != choice:
                    continue
                if search:
                    if search.isdigit() and len(search) <= 6:
                        if int(search) != p['number']:
                            continue
                    elif search not in p['post_id']:
                        continue
                selected.append((p, decision, state))
            pages = max(1, (len(selected) + size - 1) // size)
            page = min(page, pages)
            items = []
            for p, decision, state in selected[(page-1)*size:page*size]:
                items.append({k:p[k] for k in ['post_id','number','images','pilot_number','previously_excluded']} | {'decision': decision, 'state': state, 'reason': snapshot['decisions'].get(p['post_id'], {}).get('reason','')})
            return self.send_json(200, {'posts': items, 'page': page, 'pages': pages, 'matches': len(selected), 'summary': summary(snapshot)})
        match = re.fullmatch(r'/images/([0-9a-f]{64})\.jpg', path)
        if match and match.group(1) in self.server.images:
            try:
                return self.send_bytes(200, self.server.image(match.group(1)), 'image/jpeg')
            except (OSError, ValueError, KeyError, zipfile.BadZipFile):
                return self.send_json(500, {'error': '画像の読込・整合性検査に失敗しました'})
        static = {'/': ('index.html','text/html; charset=utf-8'), '/app.js':('app.js','text/javascript; charset=utf-8'), '/style.css':('style.css','text/css; charset=utf-8')}
        if path in static:
            name, mime = static[path]
            return self.send_bytes(200, (self.server.web_root/name).read_bytes(), mime)
        self.send_json(404, {'error':'Not found'})

    def do_POST(self):
        if not self.local_host() or self.headers.get('Origin') not in {f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}'} or self.headers.get('X-Review-Token') != self.server.token:
            return self.send_json(403, {'error':'Invalid local session'})
        try:
            length = int(self.headers.get('Content-Length','0'))
            if not 0 < length <= 1000000:
                raise ValueError('Invalid request size')
            item = json.loads(self.rfile.read(length))
            if self.path == '/api/decisions':
                result = self.server.store.apply(item['post_ids'], item['decision'], item.get('reason',''), item['revision'], item.get('pending_only', False))
            elif self.path == '/api/undo':
                result = self.server.store.undo(item['revision'])
            elif self.path == '/api/complete':
                result = self.server.store.complete(item['revision'], item.get('confirmation'))
            else:
                return self.send_json(404, {'error':'Not found'})
            return self.send_json(200, summary(result))
        except FileExistsError as e:
            return self.send_json(409, {'error':str(e)})
        except (ValueError, KeyError, TypeError) as e:
            return self.send_json(400, {'error':str(e)})
        except (OSError, sqlite3.Error):
            return self.send_json(500, {'error':'保存できませんでした。再試行してください。'})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8767)
    parser.add_argument('--open', action='store_true')
    parser.add_argument('--db', type=Path, default=ROOT / 'private/screening/data-v1.sqlite3')
    args = parser.parse_args()
    url = f'http://127.0.0.1:{args.port}'
    if args.open:
        try:
            with urlopen(url+'/api/health', timeout=1) as r:
                health = json.load(r)
            if health.get('app') == 'illustration-human-screening':
                webbrowser.open(url)
                return
        except (OSError, ValueError):
            pass
    index = build_index()
    server = ScreeningServer(('127.0.0.1',args.port), index, args.db, bundle_root(ROOT))
    print(f"{url} | {index['total_posts']} posts | {index['total_images']} images | production blocked", flush=True)
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
