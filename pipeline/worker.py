"""python -m pipeline.worker --help. This CLI handles I/O, never image inference."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random
import sys
import time

from . import contract
from .bundles import download, unpack
from .common import atomic_write, canonical, digest, read_json
from .git_queue import Conflict, GitQueue, LostLease, QueueError, safe_id

ROOT = Path(__file__).resolve().parents[1]


def check_config(path):
    config = read_json(path)
    catalog = read_json(ROOT / 'data/catalog.json')
    assert digest(ROOT / 'data/catalog.json') == config['catalog_sha256'], 'Catalog version changed'
    assert digest(ROOT / 'review/terra_labeling_manual_draft.md') == config['manual_sha256'], 'Manual version changed'
    assert digest(ROOT / 'pipeline/contract.py') == config['contract_sha256'], 'Schema changed; create a new run'
    assert config['schema_version'] == contract.VERSION
    safe_id(config['run_id'])
    return config, catalog


def provenance(config, manifest):
    return {k: config[k] for k in ('run_id', 'schema_version', 'catalog_sha256', 'manual_sha256', 'contract_sha256',
                                  'model_id', 'reasoning_effort')} | {'job_id': manifest['job_id']}


def records_in(folder, manifest, config):
    by_id = {p['post_id']: p for p in manifest['posts']}
    out = {}
    for f in sorted((folder / 'results').glob('*.json')):
        pid = f.stem
        assert pid in by_id, 'A saved result does not belong to this job'
        row = read_json(f)
        contract.validate(row, by_id[pid], provenance(config, manifest))
        out[pid] = row
    return out


def run(args):
    assert __debug__, 'Do not run with Python -O: validation must be enabled'
    config, catalog = check_config(args.config)
    jobs = {j['job_id']: j for j in catalog['jobs'] if j['job_id'] in config['job_ids']}
    runtime = ROOT / '.runtime' / config['run_id']
    remote = args.remote or config['remote']
    if args.command == 'contract':
        print(json.dumps({'image': contract.IMAGE_FIELDS, 'depiction': contract.DEPICTION_FIELDS,
                          'context': contract.CONTEXT_FIELDS}, ensure_ascii=False, indent=2))
        return
    if args.command == 'claim':
        safe_id(args.worker)
        # Randomized per worker/run: avoid a herd competing for job 1.
        candidates = list(jobs.values())
        random.Random(config['run_id'] + args.worker).shuffle(candidates)
        with GitQueue(remote, config['run_id'], config['catalog_sha256']) as queue:
            known = queue.heads()
            candidates.sort(key=lambda j: j['job_id'] in known)
            for job in candidates:
                try:
                    lease = queue.reserve(job['job_id'], args.worker)
                except Conflict:
                    continue
                if not lease:
                    continue
                folder = runtime / job['job_id']
                atomic_write(folder / 'lease.json', canonical(lease))
                try:
                    if args.bundle_dir:
                        bundle = Path(args.bundle_dir) / job['asset']
                    else:
                        bundle = folder / job['asset']
                        download(catalog, job, bundle, read_json(ROOT / 'data/assets.json'))
                    manifest = unpack(bundle, job, folder)
                    restored = queue.restore(job['job_id'], folder / 'results')
                    # Existing checkpoint results belong to the same pinned run, not worker ID.
                    records_in(folder, manifest, config)
                    print(json.dumps({'job_id': job['job_id'], 'folder': str(folder), 'restored': restored,
                                      'post_count': len(manifest['posts']), 'lease_until': lease['lease_until']}))
                    return
                except Exception:
                    queue.release(job['job_id'], lease['token'], 'input_preparation_failed')
                    raise
        print(json.dumps({'status': 'no_available_job', 'instruction': 'Stop. Retry in >= 120 seconds; do not spin.'}))
        return
    if args.command == 'status':
        with GitQueue(remote, config['run_id'], config['catalog_sha256']) as queue:
            heads = queue.heads()
            counts = {'unclaimed': len(set(jobs) - set(heads))}
            for job_id in sorted(set(jobs) & set(heads)):
                _, state = queue.read(job_id)
                key = state['status']
                if key == 'leased' and state['lease_until'] + 120 <= time.time():
                    key = 'expired'
                counts[key] = counts.get(key, 0) + 1
            print(json.dumps(counts))
        return
    if args.job not in jobs:
        raise ValueError('Job is not enabled in this run')
    job = jobs[args.job]
    folder = runtime / args.job
    manifest = read_json(folder / 'manifest.json')
    assert digest(folder / 'manifest.json') == job['manifest_sha256']
    lease = read_json(folder / 'lease.json')
    rows = records_in(folder, manifest, config)
    if args.command == 'next':
        for post in manifest['posts']:
            if post['post_id'] in rows:
                continue
            draft = contract.template(post, provenance(config, manifest), worker_id=lease['worker_id'])
            atomic_write(folder / 'draft.json', canonical(draft))
            print(json.dumps({'post_id': post['post_id'], 'images': [str(folder / i['path']) for i in post['images']],
                              'draft': str(folder / 'draft.json'), 'instructions': 'View every image using an actual vision tool; edit draft then save.'}))
            return
        print(json.dumps({'status': 'local_batch_complete', 'next': 'checkpoint, then finish'}))
        return
    if args.command == 'save':
        row = read_json(args.input or folder / 'draft.json')
        if row['execution']['finished_at'] is None:
            row['execution']['finished_at'] = datetime.now(timezone.utc).isoformat()
        post = next(p for p in manifest['posts'] if p['post_id'] == row['post_id'])
        contract.validate(row, post, provenance(config, manifest))
        # Verify ownership before accepting new work; stale workers fail closed.
        with GitQueue(remote, config['run_id'], config['catalog_sha256']) as queue:
            queue._owned(args.job, lease['token'])
        path = folder / 'results' / (row['post_id'] + '.json')
        if path.exists() and path.read_bytes() != canonical(row):
            raise Conflict('Existing local answer differs; use a new review run')
        atomic_write(path, canonical(row))
        atomic_write(args.input or folder / 'draft.json', canonical(row))
        print(json.dumps({'saved': row['post_id'], 'local_total': len(rows | {row['post_id']: row})}))
        return
    with GitQueue(remote, config['run_id'], config['catalog_sha256']) as queue:
        if args.command == 'checkpoint':
            sha = queue.checkpoint(args.job, lease['token'], rows, manifest=manifest)
        elif args.command == 'finish':
            assert set(rows) == set(job['post_ids']), 'Local batch is incomplete'
            sha = queue.finish(args.job, lease['token'], job['post_ids'])
        elif args.command == 'release':
            sha = queue.release(args.job, lease['token'], 'worker_yielded')
        else:
            raise ValueError('Unknown command')
        print(json.dumps({'status': args.command, 'remote_head': sha}))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config', default=str(ROOT / 'runs/pilot-v2-001.json'))
    p.add_argument('--remote', help='Testing only: override remote with a local bare repository')
    p.add_argument('command', choices=['contract', 'claim', 'next', 'save', 'checkpoint', 'finish', 'release', 'status'])
    p.add_argument('--worker', default='worker-01')
    p.add_argument('--job')
    p.add_argument('--input')
    p.add_argument('--bundle-dir')
    try:
        run(p.parse_args())
    except (AssertionError, ValueError, Conflict, LostLease, QueueError, OSError) as e:
        print(json.dumps({'error': type(e).__name__, 'message': str(e)}), file=sys.stderr)
        raise SystemExit(2)


if __name__ == '__main__':
    main()
