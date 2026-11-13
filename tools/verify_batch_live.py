"""Verify accepted metadata and actual tool events without opening any images."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline_production import worker as base
from pipeline_production.common import canonical, read_json, atomic_write


def verify(evidence):
    config, catalog = base.check_config(ROOT / 'runs/production-v4-001.json')
    jobs = {j['job_id']: j for j in catalog['jobs']}
    started = datetime.strptime(evidence['started_at_utc'], '%Y-%m-%d %H:%M:%S UTC').replace(tzinfo=timezone.utc)
    checked = {}; next_times = []; save_times = []; label_times = []
    for worker, bundle in evidence['workers'].items():
        trace = bundle['trace']; rows = bundle['records']; details = []
        for pid in bundle['ids']:
            row = rows[pid]; job = row['provenance']['job_id']; spec = jobs[job]
            post = next(p for p in spec['manifest']['posts'] if p['post_id'] == pid)
            head = bundle.get('post_heads', {}).get(pid, bundle.get('head'))
            base.validate_result(row, post, config, spec['manifest'])
            assert row['execution']['worker_id'] == worker
            assert datetime.fromisoformat(row['execution']['started_at']) >= started, 'Old draft is not a new-post probe'
            entry = next(x for x in trace['nexts'] if x['post_id'] == pid)
            save = next(x for x in trace['saves'] if x['saved_locally'] == pid and x['pos'] > entry['pos'])
            checkpoint = next(x for x in trace['checkpoints'] if x['remote_head'] == head and x['pos'] > save['pos'])
            assert len(entry['images']) == len(post['images'])
            views = []
            for image in post['images']:
                path = next(p for p in entry['images'] if p.endswith('/' + image['path']))
                view = next(v for v in trace['views'] if v['path'] == path and entry['pos'] < v['pos'] < save['pos'])
                audit = next(a for a in reversed(trace['isolations']) if a['pos'] < view['pos'])
                assert audit['excluded_images_found'] == 0
                views.append(dict(media_index=image['media_index'], sha256=image['sha256'],
                    view_event_id=view['id'], next_event_id=entry['id'], isolation_event_id=audit['id']))
            duration = (datetime.fromisoformat(row['execution']['finished_at']) - datetime.fromisoformat(row['execution']['started_at'])).total_seconds()
            assert duration >= 0
            next_times.append(entry['durationMs']); save_times.append(save['durationMs']); label_times.append(duration)
            details.append(dict(post_id=pid, record_sha256=hashlib.sha256(canonical(row)).hexdigest(),
                job_id=job, checkpoint_head=head, checkpoint_event_id=checkpoint['id'], views=views,
                next_command_ms=entry['durationMs'], save_command_ms=save['durationMs'], draft_to_finished_seconds=duration))
        checked[worker] = dict(jobs=sorted({x['job_id'] for x in details}), checked_posts=len(details), details=details)
    def stats(values):
        return dict(min=min(values), median=statistics.median(values), max=max(values)) if values else None
    return dict(workers=checked, total_posts=sum(x['checked_posts'] for x in checked.values()),
        next_command_ms=stats(next_times), save_command_ms=stats(save_times),
        draft_to_finished_seconds=stats(label_times),
        scope='Metadata/schema, allowed next paths, actual image-view events, isolation and shared acceptance. No research pixels opened by coordinator. Timings include command grouping; this is not a controlled speed benchmark.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('input'); parser.add_argument('output')
    args = parser.parse_args(); result = verify(read_json(args.input))
    atomic_write(args.output, canonical(result))
    print(json.dumps(dict(workers=len(result['workers']), posts=result['total_posts'],
        next_ms=result['next_command_ms'], save_ms=result['save_command_ms']), ensure_ascii=False))
