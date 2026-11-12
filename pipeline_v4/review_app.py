"""Local visual review of a completed pilot. No labeling, queue writes, or network downloads."""
import argparse
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import secrets
import threading
from urllib.parse import urlsplit
from urllib.request import urlopen
import webbrowser

from .bundles import unpack
from pipeline.human_source import bundle_root
from .common import atomic_write, canonical
from .disposition import is_exclusion
from .isolation import load_policy, check_post_files
from .worker import check_config, validate_result

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / 'review_app_v4'
STATUSES = {'pending', 'ok', 'issue', 'hold'}


def load_pilot(root=ROOT, config_path=None, recovered=None):
    root = Path(root)
    config, catalog = check_config(config_path or root / 'runs/pilot-v4-002.json')
    modern = config['schema_version'] == 'v4-1'
    folder = Path(recovered) if recovered else (root / '.runtime/recovered' / config['run_id'] if modern else root / '.runtime/pilot-recovered')
    policy = load_policy(config, root) if modern else None
    source = root / 'dist' / catalog['dataset_version'] if modern else bundle_root(root)
    rows = {}
    image_paths = {}
    exclusions = []
    blocked_hashes = set()
    for job in catalog['jobs']:
        if job['job_id'] not in config['job_ids']:
            continue
        saved = folder / job['job_id']
        state = json.loads((saved / 'state.json').read_text(encoding='utf-8'))
        raw = (saved / 'labels.jsonl').read_bytes()
        if state['status'] != 'completed' or hashlib.sha256(raw).hexdigest() != state['result_sha256']:
            raise ValueError('Completed result checksum mismatch')
        destination = root / '.runtime/review-images' / config['run_id'] / job['job_id']
        manifest = unpack(source / job['asset'], job, destination, exclusion_policy=policy)
        posts = {p['post_id']: p for p in manifest['posts']}
        batch = [json.loads(line) for line in raw.splitlines()]
        if len(batch) != len(posts) or {r['post_id'] for r in batch} != set(posts):
            raise ValueError('Result coverage mismatch')
        for row in batch:
            post = posts[row['post_id']]
            validate_result(row, post, config, manifest)
            if is_exclusion(row):
                exclusions.append({'post_id':row['post_id'], 'reason':row['reason']})
                blocked_hashes.update(i['sha256'] for i in post['images'])
                continue
            if policy:
                check_post_files(destination, post, policy)
            if row['post_id'] in rows:
                raise ValueError('Duplicate post')
            rows[row['post_id']] = row
            for image in posts[row['post_id']]['images']:
                image_paths[image['sha256']] = destination / image['path']
    # Refused posts and identical image bytes never enter the review image route.
    ordered = [rows[k] for k in sorted(rows) if not any(i['sha256'] in blocked_hashes for i in rows[k]['images'])]
    visible_hashes = {i['sha256'] for r in ordered for i in r['images']}
    image_paths = {sha:path for sha,path in image_paths.items() if sha in visible_hashes}
    fingerprint = hashlib.sha256(b''.join(canonical(r) for r in ordered)).hexdigest()
    return {'run_id': config['run_id'], 'schema_version':config['schema_version'], 'fingerprint': fingerprint,
            'posts': ordered, 'exclusions':exclusions}, image_paths


class ReviewStore:
    def __init__(self, path, dataset):
        self.path = Path(path)
        self.dataset = dataset
        self.posts = {p['post_id']: p for p in dataset['posts']}
        self.lock = threading.Lock()
        self.state = {'version': 1, 'run_id': dataset['run_id'], 'dataset_sha256': dataset['fingerprint'],
                      'method': 'human_quick_review_with_ai_labels_visible', 'reviews': {}}
        if self.path.exists():
            self.state = json.loads(self.path.read_text(encoding='utf-8'))
            if self.state['dataset_sha256'] != dataset['fingerprint']:
                raise ValueError('Review belongs to different source results')

    def snapshot(self):
        with self.lock:
            return json.loads(json.dumps(self.state, ensure_ascii=False))

    def save(self, item):
        pid = item.get('post_id')
        if pid not in self.posts or item.get('status') not in STATUSES:
            raise ValueError('Invalid post or review status')
        note = item.get('note', '')
        flags = item.get('flags', [])
        media = item.get('displayed_media', [])
        if not isinstance(note, str) or len(note) > 5000:
            raise ValueError('Note must be at most 5000 characters')
        if not isinstance(flags, list) or len(flags) > 150 or any(not isinstance(f, str) or not re.fullmatch(r'[a-zA-Z0-9_.:-]{1,140}', f) for f in flags):
            raise ValueError('Invalid field flags')
        valid_media = {i['media_index'] for i in self.posts[pid]['images']}
        if not isinstance(media, list) or any(type(n) is not int or n not in valid_media for n in media):
            raise ValueError('Invalid displayed image indices')
        if type(item.get('revision')) is not int:
            raise ValueError('Missing revision')
        with self.lock:
            old = self.state['reviews'].get(pid, {})
            revision = old.get('revision', 0)
            if item['revision'] != revision:
                raise FileExistsError('別の画面で確認結果が更新されています。再読み込みしてから入力してください。')
            result = {'post_id': pid, 'status': item['status'], 'note': note,
                      'flags': sorted(set(flags)), 'displayed_media': sorted(set(media)),
                      'revision': revision + 1, 'updated_at': datetime.now(timezone.utc).isoformat()}
            # Build a separate snapshot so disk failures never become successful in-memory saves.
            updated = dict(self.state, reviews=dict(self.state['reviews'], **{pid: result}))
            atomic_write(self.path, canonical(updated))
            self.state = updated
            return dict(result)


class ReviewServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, dataset, image_paths, review_path, web_root=WEB):
        super().__init__(address, Handler)
        self.dataset, self.image_paths, self.web_root = dataset, image_paths, Path(web_root)
        self.store = ReviewStore(review_path, dataset)
        self.token = secrets.token_urlsafe(32)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def send_bytes(self, status, payload, mime='application/json; charset=utf-8', extra=None):
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Cache-Control', 'no-store' if not mime.startswith('image/') else 'private, max-age=86400')
        self.send_header('Content-Security-Policy', "default-src 'self'; img-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'self'; base-uri 'none'; form-action 'none'")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(payload)

    def send_json(self, status, value):
        self.send_bytes(status, json.dumps(value, ensure_ascii=False).encode('utf-8'))

    def local_host(self):
        return self.headers.get('Host') in {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}

    def do_GET(self):
        if not self.local_host():
            return self.send_json(403, {'error': 'Local access only'})
        path = urlsplit(self.path).path
        if path == '/api/health':
            return self.send_json(200, {'app': 'illustration-pilot-review', 'run_id': self.server.dataset['run_id']})
        if path == '/api/data':
            return self.send_json(200, {**self.server.dataset, 'review': self.server.store.snapshot(), 'token': self.server.token})
        if path == '/api/export':
            return self.send_bytes(200, canonical(self.server.store.snapshot()), extra={'Content-Disposition': 'attachment; filename="pilot-human-review.json"'})
        if path.startswith('/images/'):
            match = re.fullmatch(r'/images/([0-9a-f]{64})\.jpg', path)
            image = self.server.image_paths.get(match.group(1)) if match else None
            if image:
                payload = image.read_bytes()
                if hashlib.sha256(payload).hexdigest() != match.group(1):
                    return self.send_json(409, {'error':'Image checksum mismatch'})
                return self.send_bytes(200, payload, 'image/jpeg')
        static = {'/': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'text/javascript; charset=utf-8'), '/style.css': ('style.css', 'text/css; charset=utf-8')}
        if path in static:
            filename, mime = static[path]
            return self.send_bytes(200, (self.server.web_root / filename).read_bytes(), mime)
        return self.send_json(404, {'error': 'Not found'})

    def do_POST(self):
        if not self.local_host():
            return self.send_json(403, {'error': 'Local access only'})
        allowed = {f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}'}
        if self.headers.get('Origin') not in allowed or self.headers.get('X-Review-Token') != self.server.token:
            return self.send_json(403, {'error': 'Invalid review session'})
        if self.path != '/api/review':
            return self.send_json(404, {'error': 'Not found'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 32000:
                raise ValueError('Invalid payload size')
            item = json.loads(self.rfile.read(length))
            if not isinstance(item, dict):
                raise ValueError('Expected an object')
            return self.send_json(200, self.server.store.save(item))
        except FileExistsError as e:
            return self.send_json(409, {'error': str(e)})
        except (ValueError, TypeError) as e:
            return self.send_json(400, {'error': str(e)})
        except OSError:
            return self.send_json(500, {'error': '保存できませんでした。ディスクの空き容量や書き込み権限を確認してください。'})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8766)
    parser.add_argument('--config', type=Path, default=ROOT / 'runs/pilot-v4-002.json')
    parser.add_argument('--recovered', type=Path)
    parser.add_argument('--open', action='store_true')
    parser.add_argument('--review-file', type=Path)
    args = parser.parse_args()
    expected_run = json.loads(args.config.read_text(encoding='utf-8'))['run_id']
    if args.open:
        try:
            with urlopen(f'http://127.0.0.1:{args.port}/api/health', timeout=1) as response:
                running = json.load(response)
            if running.get('app') == 'illustration-pilot-review' and running.get('run_id') == expected_run:
                webbrowser.open(f'http://127.0.0.1:{args.port}')
                return
        except (OSError, ValueError):
            pass
    data, images = load_pilot(config_path=args.config, recovered=args.recovered)
    server = ReviewServer(('127.0.0.1', args.port), data, images, args.review_file or ROOT / 'private/reviews' / (data['run_id']+'.json'))
    url = f'http://127.0.0.1:{server.server_port}'
    print(f'{url} | {len(data["posts"])} posts | {len(images)} images', flush=True)
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
