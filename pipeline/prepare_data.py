"""Create immutable, blinded job bundles from the supplied read-only database/ZIP."""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import random
import sqlite3
import zipfile

from .common import atomic_write, canonical, digest


def build(db, archive, output, catalog_path, batch_size=50):
    db, output = Path(db).resolve(), Path(output)
    output.mkdir(parents=True, exist_ok=True)
    before = digest(db)
    con = sqlite3.connect(db.as_uri() + '?mode=ro&immutable=1', uri=True)
    media = defaultdict(list)
    for pid, index, sha, ext in con.execute('SELECT post_id,media_index,sha256,ext FROM tmedia ORDER BY post_id,media_index'):
        media[pid].append({'media_index': index, 'sha256': sha, 'path': 'images/' + sha + '.' + ext.lstrip('.')})
    posts = [{'post_id': pid, 'images': media[pid]} for (pid,) in con.execute('SELECT post_id FROM targets ORDER BY qno')]
    human = {pid: {'excluded': bool(ex), 'answers': json.loads(ans)} for pid, ex, ans in con.execute('SELECT post_id,is_excluded,answers_json FROM results')}
    con.close()
    assert len({p['post_id'] for p in posts}) == len(posts)
    assert all(p['images'] for p in posts)
    # Group exact image duplicates so calibration/evaluation sets cannot share a hash.
    parent = {p['post_id']: p['post_id'] for p in posts}
    def root(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    owner = {}
    for p in posts:
        for im in p['images']:
            sha = im['sha256']
            if sha in owner:
                parent[root(p['post_id'])] = root(owner[sha])
            owner[sha] = p['post_id']
    groups = defaultdict(list)
    for p in posts:
        groups[root(p['post_id'])].append(p)
    ordered = list(groups.values())
    random.Random(20261111).shuffle(ordered)
    # Deterministic random calibration/evaluation groups, whole duplicate groups retained.
    splits = {'calibration': [], 'evaluation': [], 'production': []}
    for group in ordered:
        split = 'calibration' if len(splits['calibration']) < 100 else 'evaluation' if len(splits['evaluation']) < 100 else 'production'
        splits[split].extend(group)
    jobs, verified = [], set()
    with zipfile.ZipFile(archive) as src:
        entries = {Path(i.filename).name: i for i in src.infolist() if i.filename.lower().endswith('.jpg')}
        for split, selected in splits.items():
            # Bound both count and byte size; an individual post is never split.
            batches, batch, size = [], [], 0
            for p in selected:
                psize = sum(entries[Path(i['path']).name].file_size for i in p['images'])
                if batch and (len(batch) >= batch_size or size + psize > 64 * 1024 * 1024):
                    batches.append(batch)
                    batch, size = [], 0
                batch.append(p)
                size += psize
            if batch:
                batches.append(batch)
            for seq, batch in enumerate(batches, 1):
                job_id = f'{split[:3]}-{seq:04d}'
                manifest = {'dataset_version': 'data-v1', 'job_id': job_id, 'split': split, 'posts': batch}
                mbytes = canonical(manifest)
                target = output / (job_id + '.zip')
                # Fixed ZIP metadata makes repeated builds byte-for-byte reproducible.
                with zipfile.ZipFile(target.with_suffix('.part'), 'w', compression=zipfile.ZIP_STORED) as dst:
                    def put(name, data):
                        info = zipfile.ZipInfo(name, date_time=(2026, 11, 11, 0, 0, 0))
                        info.external_attr = 0o100644 << 16
                        dst.writestr(info, data)
                    put('manifest.json', mbytes)
                    for path in sorted({i['path'] for p in batch for i in p['images']}):
                        data = src.read(entries[Path(path).name])
                        sha = hashlib.sha256(data).hexdigest()
                        if sha != Path(path).stem:
                            raise ValueError('Source image SHA-256 mismatch: ' + Path(path).name)
                        verified.add(sha)
                        put(path, data)
                target.with_suffix('.part').replace(target)
                jobs.append({'job_id': job_id, 'split': split, 'post_ids': [p['post_id'] for p in batch],
                             'asset': target.name, 'bytes': target.stat().st_size, 'sha256': digest(target),
                             'manifest_sha256': hashlib.sha256(mbytes).hexdigest(),
                             'image_references': sum(len(p['images']) for p in batch)})
                if len(jobs) % 25 == 0:
                    print(json.dumps({'bundles_written': len(jobs), 'images_hash_verified': len(verified)}), flush=True)
    catalog = {'dataset_version': 'data-v1', 'repository': 'ugin-man/x-illustration-labeling',
               'release_tag': 'data-v1', 'source_db_sha256': before, 'post_count': len(posts),
               'image_references': sum(len(p['images']) for p in posts), 'unique_images': len(verified),
               'split_seed': 20261111, 'jobs': jobs}
    atomic_write(catalog_path, canonical(catalog))
    atomic_write(output / 'catalog.json', canonical(catalog))
    # Human labels and old exclusion decisions stay local and blinded from workers.
    atomic_write(Path('private') / 'human_reference.json', canonical(human))
    atomic_write(Path('private') / 'split_assignment.json', canonical({k: [p['post_id'] for p in v] for k, v in splits.items()}))
    assert digest(db) == before
    print(json.dumps({'jobs': len(jobs), 'posts': len(posts), 'unique_images_sha_verified': len(verified),
                      'bytes': sum(j['bytes'] for j in jobs), 'catalog_sha256': digest(catalog_path),
                      'splits': {k: len(v) for k, v in splits.items()}}, indent=2), flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--db', required=True)
    p.add_argument('--archive', required=True)
    p.add_argument('--output', default='dist/data-v1')
    p.add_argument('--catalog', default='data/catalog.json')
    a = p.parse_args()
    build(a.db, a.archive, a.output, a.catalog)
