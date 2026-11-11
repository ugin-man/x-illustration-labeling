"""Collect completed batches only. Preserve incomplete/unknown/failure counts explicitly."""
import argparse
from collections import Counter
import csv
import hashlib
import io
import json
from pathlib import Path

from .common import atomic_write, canonical
from .contract import COLORS, validate
from .git_queue import GitQueue
from .worker import check_config, provenance


def aggregate_hair(images, color):
    values = [i['attributes']['has_' + color + '_hair'] for i in images]
    if any(v['status'] == 'observed' and v['value'] is True for v in values):
        return 'true'
    if all(v['status'] == 'observed' and v['value'] is False for v in values):
        return 'false'
    return 'unknown'


def collect(config_path, output, remote=None):
    config, catalog = check_config(config_path)
    jobs = {j['job_id']: j for j in catalog['jobs'] if j['job_id'] in config['job_ids']}
    rows, receipts, counts = {}, {}, Counter()
    with GitQueue(remote or config['remote'], config['run_id'], config['catalog_sha256']) as q:
        heads = q.heads()
        for jid, job in jobs.items():
            if jid not in heads:
                counts['unclaimed_jobs'] += 1
                continue
            sha, state = q.read(jid)
            if state['status'] != 'completed':
                counts[state['status'] + '_jobs'] += 1
                continue
            raw = q.git('show', sha + ':labels.jsonl').stdout
            assert hashlib.sha256(raw).hexdigest() == state['result_sha256']
            manifest_bytes = q.git('show', sha + ':manifest.json').stdout
            assert hashlib.sha256(manifest_bytes).hexdigest() == job['manifest_sha256']
            manifest = json.loads(manifest_bytes)
            expected_posts = {p['post_id']: p for p in manifest['posts']}
            batch = [json.loads(line) for line in raw.splitlines()]
            assert len(batch) == len(job['post_ids']) == state['result_count']
            assert {r['post_id'] for r in batch} == set(job['post_ids'])
            for row in batch:
                validate(row, expected_posts[row['post_id']], provenance(config, manifest))
                prov = row['provenance']
                for k in ('run_id', 'catalog_sha256', 'manual_sha256', 'contract_sha256', 'schema_version', 'model_id', 'reasoning_effort'):
                    assert prov[k] == config[k], 'Result provenance mismatch'
                pid = row['post_id']
                assert pid not in rows, 'Duplicate post result across batches'
                rows[pid] = row
            receipts[jid] = {'head': sha, 'result_sha256': state['result_sha256']}
            counts['completed_visual_jobs'] += 1
    output = Path(output)
    ordered = [rows[k] for k in sorted(rows)]
    atomic_write(output / 'labels.jsonl', b''.join(canonical(r) for r in ordered))
    table = io.StringIO(newline='')
    columns = ['post_id', 'image_count', 'visual_technical_failure', 'context_state', 'creation', *['has_' + c + '_hair' for c in COLORS]]
    writer = csv.DictWriter(table, fieldnames=columns)
    writer.writeheader()
    reviews = []
    for r in ordered:
        failure = any(not i['viewed'] for i in r['images'])
        counts['posts_with_visual_failure'] += int(failure)
        counts['context_' + r['context']['state']] += 1
        creation = r['context']['attributes']['creation']
        writer.writerow({'post_id': r['post_id'], 'image_count': len(r['images']), 'visual_technical_failure': failure,
                         'context_state': r['context']['state'], 'creation': creation['value'] or creation['status'],
                         **{'has_' + c + '_hair': aggregate_hair(r['images'], c) for c in COLORS}})
        # Deterministic 2% random audit, separately flagged from targeted failure reviews.
        audit = int(hashlib.sha256((config['run_id'] + r['post_id']).encode()).hexdigest()[:8], 16) % 50 == 0
        if failure or r['review_flags'] or audit:
            reviews.append({'post_id': r['post_id'], 'random_audit': audit, 'visual_failure': failure, 'flags': r['review_flags']})
    atomic_write(output / 'posts.csv', ('\ufeff' + table.getvalue()).encode('utf-8'))
    atomic_write(output / 'review_queue.jsonl', b''.join(canonical(r) for r in reviews))
    summary = {'run_id': config['run_id'], 'processed_posts': len(rows), 'expected_posts': sum(len(j['post_ids']) for j in jobs.values()),
               'counts': dict(counts), 'jobs': receipts, 'note': 'Visual job completion does not imply context completion or correctness.'}
    atomic_write(output / 'receipt.json', canonical(summary))
    print(json.dumps({k: v for k, v in summary.items() if k != 'jobs'}))


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--config', default='runs/pilot-v2-001.json')
    p.add_argument('--output', default='.runtime/collected')
    p.add_argument('--remote')
    a = p.parse_args()
    collect(a.config, a.output, a.remote)
