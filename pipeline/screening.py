"""Local human screening metadata and decisions. Never invokes an image model."""
from datetime import datetime, timezone
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import threading
import zipfile

from .common import atomic_write, canonical, digest, read_json
from .human_source import bundle_root

ROOT = Path(__file__).resolve().parents[1]
DECISIONS = {'pending', 'include', 'exclude', 'hold'}
REASONS = {'sexual_content', 'uncertain', 'out_of_scope', 'other', ''}


def now():
    return datetime.now(timezone.utc).isoformat()


def build_index(root=ROOT):
    catalog_path = root / 'data/catalog.json'
    fingerprint = digest(catalog_path)
    catalog = read_json(catalog_path)
    pilot_ids = set()
    for j in catalog['jobs']:
        if j['job_id'] in {'cal-0001', 'cal-0002'}:
            pilot_ids.update(j['post_ids'])
    pilot_numbers = {pid: i + 1 for i, pid in enumerate(sorted(pilot_ids))}
    previous = root / 'private/human_reference.json'
    old_excluded = {p for p, r in read_json(previous).items() if r['excluded']} if previous.exists() else set()
    posts, seen = [], set()
    for job in catalog['jobs']:
        if Path(job['asset']).name != job['asset']:
            raise ValueError('Unsafe asset path')
        with zipfile.ZipFile(bundle_root(root) / job['asset']) as archive:
            raw = archive.read('manifest.json')
        if hashlib.sha256(raw).hexdigest() != job['manifest_sha256']:
            raise ValueError('Manifest checksum mismatch: ' + job['job_id'])
        manifest = json.loads(raw)
        if manifest['job_id'] != job['job_id'] or [p['post_id'] for p in manifest['posts']] != job['post_ids']:
            raise ValueError('Manifest/catalog coverage mismatch')
        for post in manifest['posts']:
            pid = post['post_id']
            if pid in seen:
                raise ValueError('Duplicate post ID')
            seen.add(pid)
            for im in post['images']:
                if len(im['sha256']) != 64 or im['path'] != 'images/' + im['sha256'] + '.jpg':
                    raise ValueError('Unexpected image path')
            posts.append(dict(post, asset=job['asset'], split=job['split'], pilot_number=pilot_numbers.get(pid), previously_excluded=pid in old_excluded))
    posts.sort(key=lambda p: p['post_id'])
    for number, post in enumerate(posts, 1):
        post['number'] = number
    if len(posts) != catalog['post_count'] or sum(len(p['images']) for p in posts) != catalog['image_references']:
        raise ValueError('Dataset coverage mismatch')
    return {'version': 1, 'dataset_version': catalog['dataset_version'], 'catalog_sha256': fingerprint,
            'total_posts': len(posts), 'total_images': catalog['image_references'], 'posts': posts}


def effective_exclusions(index, decisions):
    direct = {pid for pid, r in decisions.items() if r['decision'] == 'exclude'}
    hashes = {im['sha256'] for p in index['posts'] if p['post_id'] in direct for im in p['images']}
    effective = {p['post_id'] for p in index['posts'] if any(im['sha256'] in hashes for im in p['images'])}
    return direct, effective, hashes


class ScreeningStore:
    def __init__(self, path, index):
        self.path, self.index = Path(path), index
        self.ids = {p['post_id'] for p in index['posts']}
        self.lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);'
                             'CREATE TABLE IF NOT EXISTS decisions (post_id TEXT PRIMARY KEY, decision TEXT NOT NULL, reason TEXT NOT NULL, updated_at TEXT NOT NULL);')
            existing = db.execute("SELECT value FROM meta WHERE key='catalog_sha256'").fetchone()
            if existing and existing[0] != index['catalog_sha256']:
                raise ValueError('Screening belongs to another dataset')
            for key, val in {'catalog_sha256': index['catalog_sha256'], 'revision': '0', 'completed_at': '', 'undo': ''}.items():
                db.execute('INSERT OR IGNORE INTO meta VALUES (?,?)', (key, val))

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def _read(self, db):
        meta = dict(db.execute('SELECT key,value FROM meta').fetchall())
        decisions = {r['post_id']: dict(r) for r in db.execute('SELECT * FROM decisions')}
        return meta, decisions

    def _snapshot(self, meta, decisions):
        direct, effective, hashes = effective_exclusions(self.index, decisions)
        counts = dict(include=0, exclude=len(direct), linked_exclude=len(effective - direct), hold=0, pending=0)
        for pid in self.ids - effective:
            counts[decisions.get(pid, {}).get('decision', 'pending')] += 1
        return {'catalog_sha256': self.index['catalog_sha256'], 'revision': int(meta['revision']),
                'total_posts': self.index['total_posts'], 'total_images': self.index['total_images'],
                'counts': counts, 'completed_at': meta['completed_at'] or None, 'can_undo': bool(meta['undo']),
                'production_started': False, 'launch_state': 'blocked_requires_separate_user_instruction',
                'effective_excluded_ids': sorted(effective), 'excluded_image_sha256': sorted(hashes), 'decisions': decisions}

    def snapshot(self):
        with self.lock, self.connect() as db:
            return self._snapshot(*self._read(db))

    def _assert_revision(self, meta, expected):
        if type(expected) is not int or expected != int(meta['revision']):
            raise FileExistsError('別の画面で更新されています。再読み込みしてから操作してください。')

    def apply(self, ids, decision, reason, expected_revision, pending_only=False):
        if not isinstance(ids, list) or not 1 <= len(ids) <= 5000 or any(not isinstance(p, str) or p not in self.ids for p in ids):
            raise ValueError('Unknown or invalid post IDs')
        if decision not in DECISIONS or reason not in REASONS:
            raise ValueError('Invalid decision/reason')
        ids = list(dict.fromkeys(ids))
        with self.lock, self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            meta, decisions = self._read(db)
            self._assert_revision(meta, expected_revision)
            direct, effective, _ = effective_exclusions(self.index, decisions)
            if pending_only:
                ids = [p for p in ids if decisions.get(p, {}).get('decision', 'pending') == 'pending' and p not in effective]
            if not ids:
                return self._snapshot(meta, decisions)
            before = {p: decisions.get(p) for p in ids}
            for pid in ids:
                db.execute('INSERT OR REPLACE INTO decisions VALUES (?,?,?,?)', (pid, decision, reason if decision in {'exclude','hold'} else '', now()))
            for key, val in {'revision': str(int(meta['revision']) + 1), 'completed_at': '', 'undo': json.dumps(before, ensure_ascii=False)}.items():
                db.execute('UPDATE meta SET value=? WHERE key=?', (val, key))
            db.commit()
            return self._snapshot(*self._read(db))

    def undo(self, expected_revision):
        with self.lock, self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            meta, _ = self._read(db)
            self._assert_revision(meta, expected_revision)
            if not meta['undo']:
                raise ValueError('戻せる操作がありません。')
            for pid, old in json.loads(meta['undo']).items():
                if old is None:
                    db.execute('DELETE FROM decisions WHERE post_id=?', (pid,))
                else:
                    db.execute('INSERT OR REPLACE INTO decisions VALUES (?,?,?,?)', tuple(old[k] for k in ['post_id','decision','reason','updated_at']))
            db.execute("UPDATE meta SET value='' WHERE key IN ('undo','completed_at')")
            db.execute("UPDATE meta SET value=? WHERE key='revision'", (str(int(meta['revision']) + 1),))
            db.commit()
            return self._snapshot(*self._read(db))

    def complete(self, expected_revision, confirmation):
        with self.lock, self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            meta, decisions = self._read(db)
            self._assert_revision(meta, expected_revision)
            snapshot = self._snapshot(meta, decisions)
            if snapshot['counts']['pending'] or snapshot['counts']['hold'] or confirmation != 'human_review_complete':
                raise ValueError('未確認・保留を解消してから確認完了にしてください。')
            db.execute("UPDATE meta SET value=? WHERE key='completed_at'", (now(),))
            db.execute("UPDATE meta SET value=? WHERE key='revision'", (str(int(meta['revision']) + 1),))
            db.execute("UPDATE meta SET value='' WHERE key='undo'")
            db.commit()
            snapshot = self._snapshot(*self._read(db))
            self.write_export(snapshot)
            return snapshot

    def export(self, snapshot=None):
        snapshot = snapshot or self.snapshot()
        included = sorted(self.ids - set(snapshot['effective_excluded_ids'])) if snapshot['completed_at'] else []
        result = {k: snapshot[k] for k in ['catalog_sha256','revision','counts','completed_at','total_posts','total_images','effective_excluded_ids','excluded_image_sha256','decisions']}
        result.update(version=1, method='human_local_pre_screening', state='complete' if snapshot['completed_at'] else 'in_progress',
                      included_post_ids=included, production_authorized=False)
        result['receipt_sha256'] = hashlib.sha256(canonical(result)).hexdigest()
        return result

    def write_export(self, snapshot=None):
        result = self.export(snapshot)
        atomic_write(self.path.parent / 'screening-receipt.json', canonical(result))
        return result

    def completed_receipt(self):
        with self.lock:
            result = self.export()
            if result['state'] != 'complete':
                raise ValueError('Human screening is incomplete; no prepared input may be built.')
            return result
