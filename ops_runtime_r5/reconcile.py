"""Reconcile accepted IDs and bytes; never view images or change remote data."""
import hashlib
import json
from pathlib import Path

from pipeline_production import worker as base, disposition
from pipeline_production.common import atomic_write, canonical, read_json
from pipeline_production.git_queue import Conflict


def reconcile_results(queue, folder, config, manifest, token, worker):
    folder = Path(folder)
    head, state, metadata = queue.read_metadata(manifest['job_id'], token, worker)
    posts = {p['post_id']: p for p in manifest['posts']}
    remote_files = queue.files(head)
    accepted = set(state['completed_posts'])
    if len(accepted) != len(state['completed_posts']) or not accepted <= set(posts):
        raise Conflict('Accepted ID list is invalid for the frozen manifest')
    named = {name[5:-5] for name in remote_files if name.startswith('post-') and name.endswith('.json')}
    if named != accepted:
        raise Conflict('Accepted ID list and remote result files differ')
    remote = {}
    for pid in sorted(accepted):
        raw = queue.git('show', head + ':post-' + pid + '.json').stdout
        row = json.loads(raw)
        base.validate_result(row, posts[pid], config, manifest)
        if canonical(row) != raw:
            raise Conflict('Accepted record bytes are not canonical; preserve both copies')
        remote[pid] = raw
    local = {}
    for path in sorted((folder / 'results').glob('*.json')):
        pid = path.stem
        if pid not in posts:
            raise Conflict('Local result is outside the current manifest')
        raw = path.read_bytes()
        row = json.loads(raw)
        base.validate_result(row, posts[pid], config, manifest)
        if canonical(row) != raw:
            raise Conflict('Local result bytes are not canonical; preserve the original')
        if pid not in accepted and not disposition.is_exclusion(row) and row['execution']['worker_id'] != worker:
            raise Conflict('Unaccepted result belongs to another worker')
        local[pid] = raw
    conflicts = [pid for pid in sorted(set(local) & accepted) if local[pid] != remote[pid]]
    if conflicts:
        # Nothing has been overwritten or removed, including other missing rows.
        raise Conflict('Accepted/local byte mismatch; preserve both: ' + ','.join(conflicts))
    restored = sorted(accepted - set(local))
    receipt = dict(operations_revision='ops-r5', job_id=manifest['job_id'], worker_id=worker,
        remote_head=head, remote_accepted_count=len(accepted), accepted_ids=sorted(accepted),
        local_saved_count_before=len(local), exact_matches=len(set(local) & accepted),
        restored_accepted_ids=restored, local_unaccepted_ids=sorted(set(local) - accepted),
        accepted_sha256={pid: hashlib.sha256(raw).hexdigest() for pid, raw in remote.items()},
        local_unaccepted_sha256={pid: hashlib.sha256(local[pid]).hexdigest() for pid in sorted(set(local) - accepted)},
        byte_conflicts=[], source_of_truth='remote_accepted_ids_and_exact_bytes')
    # Only after every candidate has passed validation and exact-byte comparison.
    for pid in restored:
        atomic_write(folder / 'results' / (pid + '.json'), remote[pid])
    atomic_write(folder / 'lease.json', canonical(dict(state, head=head)))
    digest = hashlib.sha256(canonical(receipt)).hexdigest()
    atomic_write(folder / '.ops-r5' / 'reconciliation' / (digest + '.json'), canonical(receipt))
    return receipt
