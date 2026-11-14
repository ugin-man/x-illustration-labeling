"""Fetch the current draft's post text; retry transient failures without Git."""
import argparse
import json
from pathlib import Path
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ops_batch import worker
from ops_runtime_r5.queue import blocked_posts, cache_value
from pipeline_production import context
from pipeline_production.common import atomic_write, canonical, read_json
from pipeline_production.git_queue import Conflict, QueueError

REVISION = 'text-retry-v1'


def retryable(result):
    return (result['state'] == 'technical_failure' and
            (result.get('code') is None or result['code'] in {408, 425, 429} or
             500 <= result['code'] < 600))


def fetch_text(folder, pid, *, refresh=False, attempts=10, fetch=context.fetch, sleep=time.sleep):
    """Keep all old bytes. An interrupted attempt never forbids another fetch."""
    if attempts < 1:
        raise ValueError('attempts must be positive')
    history = folder / 'context-retries' / pid
    latest = history / 'latest.json'
    legacy, _ = worker.base.context_paths(folder, pid)
    if not refresh:
        for candidate in (latest, legacy):
            if candidate.exists():
                cached = cache_value(candidate.read_bytes(), pid)
                if cached['state'] == 'available':
                    return dict(cached, cache_hit=True, attempts_this_call=0)
    for number in range(1, attempts + 1):
        path = history / (uuid.uuid4().hex + '.json')
        result = fetch(pid, path)
        cache_value(canonical(result), pid)
        atomic_write(latest, canonical(result))
        if not retryable(result) or number == attempts:
            return dict(result, cache_hit=False, attempts_this_call=number)
        sleep(min(number, 5))


def run(args):
    verified = worker.verify_revision(ROOT, args.config, args.worker)
    config, catalog = verified['config'], verified['catalog']
    worker.base.require_launch(config, catalog, ROOT)
    jobs = {j['job_id']: j for j in catalog['jobs'] if j['job_id'] in config['job_ids']}
    runtime = ROOT / '.runtime' / config['run_id']
    with worker.helpers.local_lock(runtime, args.worker):
        folder, manifest, session = worker.load_local(args, config, jobs, runtime)
        draft = read_json(folder / 'draft.json')
        pid = draft['post_id']
        # Derive the ID instead of asking the model to copy it for every request.
        if (session.get('current_post') != pid or
                draft.get('execution', {}).get('worker_id') != args.worker):
            raise Conflict('Run next for the current draft before fetching its text')
        post = worker.helpers.require_post(manifest, pid, blocked_posts(manifest, worker.metadata_of(session)))
        rows = worker.active_rows(folder, manifest, config, session)
        worker.helpers.guard_refusal(post, rows, manifest)
        if pid in rows:
            raise Conflict('This post is already saved; advance with next')
        return dict(fetch_text(folder, pid, refresh=args.refresh, attempts=args.attempts),
                    operations_revision=REVISION)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='runs/production-v4-001.json')
    parser.add_argument('--worker', required=True)
    parser.add_argument('--job', required=True)
    parser.add_argument('--refresh', action='store_true', help='Fetch again even if prior text is available')
    parser.add_argument('--attempts', type=int, default=10)
    try:
        print(json.dumps(run(parser.parse_args()), ensure_ascii=False))
    except (AssertionError, ValueError, KeyError, TypeError, QueueError, OSError) as exc:
        print(json.dumps(dict(error=type(exc).__name__, message=str(exc))), file=sys.stderr)
        raise SystemExit(2)


if __name__ == '__main__':
    main()
