"""Validate and summarize one GitHub dispatch snapshot without revealing tokens.

Read-only, metadata-only. A connected GitHub tool obtains state.json at an exact
commit and saves it privately; this helper does not contact a service or mutate
the queue. Frozen production runtime owns all queue mutation.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline_parallel.common import read_json


def snapshot(config, catalog, state, now=None):
    now = time.time() if now is None else now
    assert state['run_id'] == config['run_id']
    assert state['catalog_sha256'] == config['catalog_sha256']
    assert state['queue_version'] == config['queue_version']
    assert state['worker_ids'] == config['worker_ids']
    jobs = {job['job_id']: job for job in catalog['jobs'] if job['job_id'] in config['job_ids']}
    assert set(state['entries']) == set(jobs)
    counts = Counter()
    workers = []
    checkpointed = 0
    final_posts = 0
    retry_at = []
    for jid, entry in state['entries'].items():
        assert entry['post_count'] == len(jobs[jid]['post_ids'])
        count = entry['completed_posts']
        assert isinstance(count, int) and 0 <= count <= entry['post_count']
        checkpointed += count
        status = entry['status']
        if status in {'assigned', 'leased'}:
            wid = entry['worker_id']
            assert wid in config['worker_ids']
            assert not any(w['worker_id'] == wid for w in workers)
            if entry['lease_until'] + 120 <= now:
                observed = 'expired_available'
            elif entry['lease_until'] <= now:
                observed = 'expired_grace'
                retry_at.append(entry['lease_until'] + 120)
            else:
                observed = 'leased'
            workers.append({'worker_id': wid, 'job_id': jid, 'status': observed,
                'lease_until': entry['lease_until'], 'head': entry['head'],
                'checkpointed_posts': count, 'post_count': entry['post_count']})
            counts[observed] += 1
        elif status in {'pending', 'available'}:
            if entry.get('retry_after', 0) > now:
                counts['retry_wait'] += 1
                retry_at.append(entry['retry_after'])
            else:
                counts['available'] += 1
        elif status == 'completed':
            assert count == entry['post_count']
            counts['completed'] += 1
            final_posts += count
        elif status == 'needs_review':
            counts['needs_review'] += 1
        else:
            raise ValueError('Unknown queue status; do not guess worker actions')
    total = sum(len(j['post_ids']) for j in jobs.values())
    return {'run_id': config['run_id'], 'observed_at': now, 'index_updated_at': state['updated_at'],
            'total_posts': total, 'checkpointed_posts': checkpointed, 'completed_job_posts': final_posts,
            'unresolved_posts': total - checkpointed, 'counts': dict(counts), 'workers': workers,
            'all_jobs_completed': counts['completed'] == len(jobs),
            'claimable_jobs': counts['available'] + counts['expired_available'],
            'earliest_retry_at': min(retry_at) if retry_at else None}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--state', required=True)
    args = parser.parse_args()
    config = read_json(args.config)
    print(json.dumps(snapshot(config, read_json(ROOT / config['catalog_path']), read_json(args.state))))
