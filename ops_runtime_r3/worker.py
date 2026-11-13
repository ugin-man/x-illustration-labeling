"""Additive ops-r3 CLI. Frozen classification rules remain authoritative."""
import argparse
import base64
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time

from pipeline_production import worker as base
from pipeline_production import context, disposition
from pipeline_production.common import atomic_write, canonical, digest, read_json
from pipeline_production.git_queue import ClaimBusy, Conflict, LostLease, QueueError
from .control import verify_revision
from .queue import OpsQueue, DEFER_REASONS, blocked_posts, deferred_record, cache_value, budget_value, merge_budget

ROOT = Path(__file__).resolve().parents[1]


def check_config(path):
    verified = verify_revision(ROOT, path, require_enabled=False)
    return verified['config'], verified['catalog'], verified['manifest']


def emit(value):
    print(json.dumps(value, ensure_ascii=False))


def utcnow():
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def local_lock(runtime, worker):
    """OS-held lock survives remote gate expiry and disappears on process exit."""
    # Keep the same OS lock across revisions; a migration must not create a
    # second independent writer lock for the same worker.
    path = runtime / '.ops-r2' / (worker + '.lock')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        stream.seek(0)
        if not stream.read(1):
            stream.write(b'0'); stream.flush()
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ClaimBusy('Another operations command for this worker is running') from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def lease_snapshot(queue, folder, job, token, worker):
    if queue.claim_gate:
        queue._owned(*queue.claim_gate)
    head, state, metadata = queue.read_metadata(job, token, worker)
    atomic_write(folder / 'lease.json', canonical(dict(state, head=head)))
    return head, state, metadata


def sync_one(queue, folder, job, token, pid, worker):
    cache, ledger = base.context_paths(folder, pid)
    head, remote_cache, remote_budget = queue.sync_context(job, token, pid,
        cache.read_bytes() if cache.exists() else None,
        ledger.read_bytes() if ledger.exists() else None, worker)
    for path, raw in ((cache, remote_cache), (ledger, remote_budget)):
        if raw is not None and (not path.exists() or path.read_bytes() != raw):
            atomic_write(path, raw)
    return head


def sync_all(queue, folder, manifest, token, worker, metadata):
    blocked = blocked_posts(manifest, metadata)
    for post in manifest['posts']:
        pid = post['post_id']
        if pid in blocked:
            continue
        cache, ledger = base.context_paths(folder, pid)
        mismatch = False
        for path, name, validator in (
                (cache, 'context-cache-' + pid + '.json', lambda raw: cache_value(raw, pid)),
                (ledger, 'context-budget-' + pid + '.json', budget_value)):
            remote = metadata.get(name)
            if remote is not None:
                validator(remote)
            if not path.exists() and remote is not None:
                atomic_write(path, remote)
            elif path.exists() and path.read_bytes() != remote:
                mismatch = True
        # An authoritative owned snapshot is already available. Identical bytes
        # and remote-only restores require no repeated Git fetch per post.
        if mismatch:
            sync_one(queue, folder, manifest['job_id'], token, pid, worker)


def checkpoint_due(folder, state, rows):
    path = folder / '.ops-r3' / 'last-label-checkpoint.json'
    last = read_json(path)['at'] if path.exists() else state['acquired_at']
    return len(set(rows) - set(state['completed_posts'])) >= 5 or time.time() - last >= 600


def note_checkpoint(folder):
    atomic_write(folder / '.ops-r3' / 'last-label-checkpoint.json', canonical({'at': time.time()}))


def require_post(manifest, pid, blocked):
    post = next((p for p in manifest['posts'] if p['post_id'] == pid), None)
    if post is None:
        raise ValueError('Post is not in the pinned current job')
    if pid in blocked:
        raise Conflict('Post or an identical attachment is deferred; do not reopen it')
    return post


def refusal_hashes(manifest, rows):
    posts = {p['post_id']: p for p in manifest['posts']}
    return {im['sha256']: row['signal'] for pid, row in rows.items()
            if disposition.is_exclusion(row) for im in posts[pid]['images']}


def guard_refusal(post, rows, manifest):
    hashes = refusal_hashes(manifest, rows)
    if any(im['sha256'] in hashes for im in post['images']):
        raise Conflict('Known policy refusal: use exclude; do not retry the input')


def history_record(folder, config, manifest, pid, worker, operation, reason):
    """Preserve original artifacts byte-for-byte, with checksums and no deletion."""
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 300:
        raise ValueError('A nonempty revision reason of at most 300 characters is required')
    paths = {'answer.json': folder / 'results' / (pid + '.json')}
    draft = folder / 'draft.json'
    if draft.exists() and read_json(draft).get('post_id') == pid:
        paths['draft.json'] = draft
    cache, ledger = base.context_paths(folder, pid)
    paths.update({'context.json': cache, 'budget.json': ledger})
    raw = {name: path.read_bytes() for name, path in paths.items() if path.exists()}
    payload = dict(operations_revision='ops-r3', record_type='unaccepted_history',
        run_id=config['run_id'], job_id=manifest['job_id'], post_id=pid,
        worker_id=worker, operation=operation, reason=reason,
        artifacts={name: {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data),
                         'base64': base64.b64encode(data).decode('ascii')} for name, data in raw.items()})
    content = canonical(payload)
    sha = hashlib.sha256(content).hexdigest()
    directory = folder / '.ops-r3' / 'history' / pid / sha
    for name, data in raw.items():
        dest = directory / name
        if dest.exists() and dest.read_bytes() != data:
            raise Conflict('Existing raw history differs')
        atomic_write(dest, data)
    atomic_write(directory / 'receipt.json', content)
    return 'audit-unaccepted-' + pid + '-' + sha + '.json', content


def assert_own_unaccepted(queue, job, token, worker, state, pid, row):
    queue._guard_post(job, state, pid)
    if disposition.is_exclusion(row):
        raise Conflict('Policy exclusion cannot be revised or deferred')
    if row.get('execution', {}).get('worker_id') != worker:
        raise Conflict('Another worker unaccepted answer cannot be changed')


def apply_deferred_cleanup(queue, folder, config, manifest, token, worker, state, metadata):
    """Recover a crash after remote defer and before local archival/removal."""
    blocked = blocked_posts(manifest, metadata)
    for pid in sorted(blocked - set(state['completed_posts'])):
        path = folder / 'results' / (pid + '.json')
        if not path.exists():
            continue
        row = read_json(path)
        assert_own_unaccepted(queue, manifest['job_id'], token, worker, state, pid, row)
        name, raw = history_record(folder, config, manifest, pid, worker, 'defer', 'deferred_active_row_cleanup')
        queue.publish_sidecars(manifest['job_id'], token, {name: raw}, worker, must_be_unaccepted=(pid,))
        _, latest, _ = lease_snapshot(queue, folder, manifest['job_id'], token, worker)
        queue._guard_post(manifest['job_id'], latest, pid)
        # Exact local path is under this owned runtime; the original is already
        # in both immutable remote history and the local raw history directory.
        path.unlink()


def checkpoint_rows(queue, folder, config, manifest, token, worker, hold=None):
    _, state, metadata = lease_snapshot(queue, folder, manifest['job_id'], token, worker)
    sync_all(queue, folder, manifest, token, worker, metadata)
    rows = base.records_in(folder, manifest, config)
    blocked = blocked_posts(manifest, metadata)
    for pid in set(rows) - set(state['completed_posts']):
        if pid in blocked:
            raise Conflict('Deferred answer remains active; run next to recover archival first')
        row = rows[pid]
        if not disposition.is_exclusion(row) and row['execution']['worker_id'] != worker:
            raise Conflict('Cannot checkpoint another worker unfinished answer')
        post = next(p for p in manifest['posts'] if p['post_id'] == pid)
        base.validate_draft(row, post, config, manifest, folder)
    sha = queue.checkpoint(manifest['job_id'], token, rows, manifest=manifest, hold=hold)
    state = json.loads(queue.git('show', sha + ':state.json').stdout)
    atomic_write(folder / 'lease.json', canonical(dict(state, head=sha)))
    note_checkpoint(folder)
    return sha, state


def exclude_command(args, queue, folder, config, manifest, token, worker, metadata):
    """Refusal metadata has priority over unrelated unfinished answer problems."""
    post = require_post(manifest, args.post, blocked_posts(manifest, metadata))
    if args.signal not in disposition.SIGNALS:
        raise ValueError('Actual model/tool refusal signal required')
    path = folder / 'results' / (args.post + '.json')
    if path.exists():
        row = read_json(path)
        if not disposition.is_exclusion(row):
            raise Conflict('Existing label cannot be replaced by exclusion')
        base.validate_result(row, post, config, manifest)
    else:
        row = disposition.create(post, base.provenance(config, manifest), worker, args.signal, args.media_index)
        atomic_write(path, canonical(row))
    sha = queue.checkpoint(args.job, token, {args.post: row}, manifest=manifest)
    lease_snapshot(queue, folder, args.job, token, worker)
    # A refusal checkpoint does not reset the normal-label checkpoint timer.
    return {'excluded_post': args.post, 'temporary': True, 'remote_head': sha, 'next': 'next'}


def context_command(args, queue, folder, manifest, token, worker, metadata):
    pid = args.post
    cache, ledger = base.context_paths(folder, pid)
    sync_one(queue, folder, manifest['job_id'], token, pid, worker)
    _, state, metadata = lease_snapshot(queue, folder, manifest['job_id'], token, worker)
    action = args.context_action
    if action == 'summary':
        return context.report(ledger)
    queue._guard_post(manifest['job_id'], state, pid)
    if action == 'fetch':
        if cache.exists():
            return read_json(cache)
        name = 'context-fetch-' + pid + '.json'
        if name in metadata:
            marker = json.loads(metadata[name])
            failure = dict(post_id=pid, state='technical_failure', text=None,
                error='prior_fetch_interrupted', attempted_at=marker['attempted_at'], recovered_at=utcnow())
            # This is a genuine recovery observation, not a made-up HTTP result.
            atomic_write(cache, canonical(failure))
            sync_one(queue, folder, manifest['job_id'], token, pid, worker)
            return failure
        marker = dict(run_id=queue.run_id, job_id=manifest['job_id'], post_id=pid,
                      record_type='context_fetch_attempt', attempted_at=utcnow())
        queue.publish_sidecars(manifest['job_id'], token, {name: canonical(marker)}, worker,
                               must_be_unaccepted=(pid,))
        # No network call occurs until the reservation is durably acknowledged.
        result = context.fetch(pid, cache)
        sync_one(queue, folder, manifest['job_id'], token, pid, worker)
        return result
    if action not in {'budget', 'search', 'page'}:
        raise ValueError('Unknown context action')
    request = getattr(args, 'request_id', None)
    op_name = None
    if action in {'search', 'page'}:
        if not isinstance(request, str) or not re.fullmatch(action + r'-[1-' + ('2' if action == 'search' else '3') + ']', request):
            raise ValueError('Use fixed --request-id ' + action + '-N; reuse the same ID on communication retries')
        op_name = 'context-op-' + pid + '-' + hashlib.sha256(request.encode()).hexdigest()[:32] + '.json'
        count_key = 'searches' if action == 'search' else 'pages'
        old = read_json(ledger) if ledger.exists() else {count_key: 0}
        ordinal = int(request.rsplit('-', 1)[1])
        if op_name in metadata or ordinal <= old[count_key]:
            return dict(context.report(ledger), permitted=False, replayed=True, request_id=request,
                        instruction='Already reserved or spent. Do not execute the external tool again.')
        if ordinal != old[count_key] + 1:
            raise ValueError('Context request IDs must be used in order')
    # Compute using the unchanged frozen budget routine in a disposable file.
    # Only a successful atomic commit may replace the active local ledger.
    with tempfile.TemporaryDirectory(prefix='ops-budget-') as temporary:
        proposed = Path(temporary) / 'budget.json'
        if ledger.exists(): atomic_write(proposed, ledger.read_bytes())
        result = context.budget(proposed, action, query=getattr(args, 'query', None))
        raw = proposed.read_bytes()
        if ledger.exists() and json.loads(raw) == read_json(ledger):
            raw = ledger.read_bytes()  # Retain original bytes when nothing was spent.
    if op_name:
        operation = dict(run_id=queue.run_id, job_id=manifest['job_id'], post_id=pid,
            record_type='context_reservation', request_id=request, action=action,
            permitted=result['permitted'], budget_sha256=hashlib.sha256(raw).hexdigest())
        queue.reserve_context_operation(manifest['job_id'], token, pid, raw,
                                        op_name, canonical(operation), worker)
    else:
        queue.sync_context(manifest['job_id'], token, pid,
                           cache.read_bytes() if cache.exists() else None, raw, worker)
    atomic_write(ledger, raw)
    # Persistence consumes wall-clock time too. Never grant a tool invocation
    # after the inherited research deadline elapsed while committing its slot.
    result['remaining_seconds'] = max(0, result['deadline'] - time.time())
    result['permitted'] = result['permitted'] and result['remaining_seconds'] > 0
    return dict(result, replayed=False, request_id=request) if op_name else result


def run(args):
    command = args.command
    verified = verify_revision(ROOT, args.config, getattr(args, 'worker', None),
        require_enabled=command not in {'status', 'contract'}, coordinator=command == 'resume-review')
    config, catalog = verified['config'], verified['catalog']
    remote = getattr(args, 'remote', None) or config['remote']
    if str(remote) != str(config['remote']):
        raise ValueError('Operations cannot override the pinned queue remote')
    jobs = {j['job_id']: j for j in catalog['jobs'] if j['job_id'] in config['job_ids']}
    runtime = ROOT / '.runtime' / config['run_id']
    worker = args.worker
    if command == 'contract':
        emit(base.schema_for(config).definition()); return
    if command not in {'status', 'release', 'hold', 'exclude'}:
        base.require_launch(config, catalog, ROOT)
    with OpsQueue(remote, config['run_id'], config['catalog_sha256'], list(jobs.values()), config['worker_ids']) as queue:
        if command == 'status':
            emit(queue.status()); return
        with local_lock(runtime, worker):
            if command == 'resume-review':
                if args.job not in jobs: raise ValueError('Job is not enabled')
                sha = queue.resume_review(args.job, jobs[args.job]['manifest'], args.reason, worker)
                emit({'status': 'available', 'job_id': args.job, 'remote_head': sha}); return
            if command == 'claim':
                result = queue.claim(worker)
                if 'lease' not in result:
                    emit(result); return
                lease = result['lease']; job = jobs[lease['job_id']]
                folder = runtime / job['job_id']
                queue.acquire_claim_gate(worker)
                atomic_write(folder / 'lease.json', canonical(lease))
                try:
                    manifest = base.prepare_job(catalog, job, folder,
                        read_json(base.pinned_path(config, 'assets_path', 'data/assets.json')),
                        base.load_policy(config, ROOT), bundle_dir=getattr(args, 'bundle_dir', None))
                    restored = queue.restore(job['job_id'], folder / 'results')
                    _, state, metadata = lease_snapshot(queue, folder, job['job_id'], lease['token'], worker)
                    sync_all(queue, folder, manifest, lease['token'], worker, metadata)
                    apply_deferred_cleanup(queue, folder, config, manifest, lease['token'], worker, state, metadata)
                    base.records_in(folder, manifest, config)
                    emit({'status': result['status'], 'job_id': job['job_id'], 'folder': str(folder),
                        'restored': restored, 'post_count': len(manifest['posts']),
                        'lease_until': state['lease_until'], 'operations_revision': 'ops-r3'}); return
                except Exception:
                    # Remote accepted rows and sidecars survive preparation failure.
                    # Do not mask a validation error by changing or deleting files.
                    raise
            if args.job not in jobs: raise ValueError('Job is not enabled in this run')
            job = jobs[args.job]; folder = runtime / args.job
            lease = read_json(folder / 'lease.json'); token = lease['token']
            if lease['worker_id'] != worker:
                raise LostLease('Local job belongs to another worker identity')
            queue.acquire_claim_gate(worker)
            _, state, metadata = lease_snapshot(queue, folder, args.job, token, worker)
            if command == 'release':
                # No bad/unaccepted answer is checkpointed during release.
                # Preserve legacy context even if answer validation would fail.
                sync_all(queue, folder, job['manifest'], token, worker, metadata)
                sha = queue.release(args.job, token, 'worker_yielded')
                current = json.loads(queue.git('show', sha + ':state.json').stdout)
                atomic_write(folder / 'lease.json', canonical(dict(current, head=sha)))
                emit({'status': 'release', 'remote_head': sha}); return
            manifest = read_json(folder / 'manifest.json')
            if digest(folder / 'manifest.json') != job['manifest_sha256']:
                raise ValueError('Local manifest differs from the pinned job')
            base.check_manifest(manifest, base.load_policy(config, ROOT))
            if command == 'exclude':
                emit(exclude_command(args, queue, folder, config, manifest, token, worker, metadata)); return
            apply_deferred_cleanup(queue, folder, config, manifest, token, worker, state, metadata)
            blocked = blocked_posts(manifest, metadata)
            if command in {'next', 'checkpoint', 'finish', 'hold'}:
                sync_all(queue, folder, manifest, token, worker, metadata)
            # Revise may fix a saved row which does not pass current validation;
            # it must still have the exact pinned provenance and own identity.
            rows = {p.stem: read_json(p) for p in (folder / 'results').glob('*.json')}
            if command != 'revise' and command != 'defer':
                rows = base.records_in(folder, manifest, config)
            if command == 'next':
                for post in manifest['posts']:
                    pid = post['post_id']
                    if pid in rows or pid in blocked: continue
                    base.check_post_files(folder, post, base.load_policy(config, ROOT))
                    refused = refusal_hashes(manifest, rows)
                    duplicate = next((im for im in post['images'] if im['sha256'] in refused), None)
                    if duplicate:
                        emit({'status': 'known_refusal_requires_exclusion', 'post_id': pid,
                            'media_index': duplicate['media_index'], 'signal': refused[duplicate['sha256']],
                            'instruction': 'Run exclude. No image paths are exposed.'}); return
                    draft_path = folder / 'draft.json'
                    draft = read_json(draft_path) if draft_path.exists() else None
                    resumed = bool(draft and draft.get('post_id') == pid
                        and draft.get('provenance') == base.provenance(config, manifest)
                        and draft.get('execution', {}).get('worker_id') == worker)
                    if not resumed:
                        if draft:
                            original = draft_path.read_bytes()
                            atomic_write(folder / '.ops-r3' / 'unsent-drafts' / (hashlib.sha256(original).hexdigest() + '.json'), original)
                        atomic_write(draft_path, canonical(base.schema_for(config).template(post, base.provenance(config, manifest), worker_id=worker)))
                    _, state, _ = lease_snapshot(queue, folder, args.job, token, worker)
                    emit({'post_id': pid, 'images': [str(folder / im['path']) for im in post['images']],
                        'draft': str(draft_path), 'resumed_draft': resumed,
                        'checkpoint_due': checkpoint_due(folder, state, rows),
                        'lease_seconds_remaining': max(0, int(state['lease_until'] - time.time()))}); return
                emit({'status': 'ordinary_posts_complete' if blocked - set(rows) else 'local_batch_complete',
                      'deferred_unresolved': len(blocked - set(rows)), 'next': 'finish'}); return
            if command == 'defer' and args.post in blocked:
                # The remote tombstone already committed (possibly before a
                # lost acknowledgement). Never resync or reopen its inputs.
                require_post(manifest, args.post, set())
                queue._guard_post(args.job, state, args.post)
                emit({'status': 'deferred', 'post_id': args.post,
                      'already_deferred': True, 'completed': False, 'next': 'next'}); return
            if command in {'context', 'exclude', 'revise', 'defer'}:
                post = require_post(manifest, args.post, blocked)
                if command != 'exclude': guard_refusal(post, rows, manifest)
            if command == 'context':
                emit(context_command(args, queue, folder, manifest, token, worker, metadata)); return
            if command in {'save', 'validate', 'revise'}:
                source = Path(args.input) if getattr(args, 'input', None) else folder / 'draft.json'
                row = read_json(source)
                post = require_post(manifest, row.get('post_id'), blocked)
                if command == 'revise' and row['post_id'] != args.post:
                    raise ValueError('Replacement draft belongs to another post')
                if disposition.is_exclusion(row): raise ValueError('Use exclude for actual policy refusals')
                guard_refusal(post, rows, manifest)
                sync_one(queue, folder, args.job, token, post['post_id'], worker)
                if row['execution']['finished_at'] is None: row['execution']['finished_at'] = utcnow()
                base.validate_draft(row, post, config, manifest, folder)
                if row['execution']['worker_id'] != worker:
                    raise Conflict('Draft belongs to another worker')
                path = folder / 'results' / (row['post_id'] + '.json')
                if command == 'validate':
                    emit({'valid': True, 'post_id': row['post_id'], 'saved': False}); return
                if command == 'revise':
                    if not path.exists(): raise ValueError('Revise requires an existing own unaccepted local answer')
                    old = read_json(path)
                    if old.get('post_id') != post['post_id'] or old.get('provenance') != base.provenance(config, manifest):
                        raise Conflict('Original answer provenance differs from the pinned post/run')
                    _, state, _ = lease_snapshot(queue, folder, args.job, token, worker)
                    assert_own_unaccepted(queue, args.job, token, worker, state, post['post_id'], old)
                    name, raw = history_record(folder, config, manifest, post['post_id'], worker, 'revise', args.reason)
                    queue.publish_sidecars(args.job, token, {name: raw}, worker, must_be_unaccepted=(post['post_id'],))
                    _, state, _ = lease_snapshot(queue, folder, args.job, token, worker)
                    queue._guard_post(args.job, state, post['post_id'])
                elif path.exists() and path.read_bytes() != canonical(row):
                    raise Conflict('Local answer differs; use revise for own unaccepted corrections')
                elif row['post_id'] in state['completed_posts']:
                    raise Conflict('Accepted answers are immutable')
                atomic_write(path, canonical(row)); atomic_write(source, canonical(row))
                emit({'saved_locally': row['post_id'], 'revised': command == 'revise',
                    'remote_accepted': False, 'checkpoint_due': checkpoint_due(folder, state, rows | {row['post_id']: row})}); return
            if command == 'defer':
                queue._guard_post(args.job, state, args.post)
                addition = {'deferred-' + args.post + '.json': canonical(deferred_record(config['run_id'], args.job, post, args.reason))}
                # Only newly blocked components belong to this transaction.
                # Resyncing *all* earlier deferred posts trips the protection
                # against reopening them and prevents a second deferral.
                affected = (blocked_posts(manifest, dict(metadata, **addition))
                            - blocked - set(state['completed_posts']))
                for pid in sorted(affected):
                    if pid in rows:
                        assert_own_unaccepted(queue, args.job, token, worker, state, pid, rows[pid])
                        if rows[pid].get('provenance') != base.provenance(config, manifest):
                            raise Conflict('Unaccepted row provenance differs; preserve it for coordinator review')
                    # Preserve all local artifacts, including a cache/ledger for
                    # which no answer has yet been saved. Conflicting bytes are
                    # evidence to retain, never permission to reset remote state.
                    cache, ledger = base.context_paths(folder, pid)
                    cache_raw = cache.read_bytes() if cache.exists() else None
                    budget_raw = ledger.read_bytes() if ledger.exists() else None
                    mismatch = False
                    try:
                        if cache_raw is not None: cache_value(cache_raw, pid)
                        remote_cache = metadata.get('context-cache-' + pid + '.json')
                        if remote_cache is not None and cache_raw is not None and remote_cache != cache_raw:
                            raise Conflict('Cache bytes differ')
                        merge_budget(metadata.get('context-budget-' + pid + '.json'), budget_raw)
                    except (Conflict, ValueError, TypeError, KeyError):
                        if args.reason != 'context_record_mismatch': raise
                        mismatch = True
                    name, raw = history_record(folder, config, manifest, pid, worker, 'defer', args.reason)
                    addition[name] = raw
                    if not mismatch:
                        sync_one(queue, folder, args.job, token, pid, worker)
                queue.publish_sidecars(args.job, token, addition, worker, must_be_unaccepted=tuple(affected))
                _, state, metadata = lease_snapshot(queue, folder, args.job, token, worker)
                apply_deferred_cleanup(queue, folder, config, manifest, token, worker, state, metadata)
                emit({'status': 'deferred', 'post_id': args.post, 'blocked_post_count': len(affected),
                      'completed': False, 'next': 'next'}); return
            if command in {'checkpoint', 'hold', 'finish'}:
                hold = None
                if command == 'hold':
                    require_post(manifest, args.post, set())
                    hold = {'post_id': args.post, 'reason': args.reason}
                if command == 'finish':
                    missing = set(job['post_ids']) - set(rows)
                    if missing - blocked:
                        raise QueueError('Ordinary posts remain unfinished')
                    if missing:
                        # A held job remains incomplete; the dispatcher permits a
                        # new claim but never counts deferred posts as completed.
                        hold = {'post_id': sorted(missing)[0], 'reason': 'input_requires_review'}
                sha, current = checkpoint_rows(queue, folder, config, manifest, token, worker, hold)
                if command == 'finish' and hold is None:
                    sha = queue.finish(args.job, token, job['post_ids'])
                    current = json.loads(queue.git('show', sha + ':state.json').stdout)
                    atomic_write(folder / 'lease.json', canonical(dict(current, head=sha)))
                emit({'status': 'needs_review' if hold else ('completed' if command == 'finish' else command),
                      'remote_head': sha, 'lease_until': current['lease_until']}); return
            raise ValueError('Unknown operations command')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--worker', required=True)
    parser.add_argument('command', choices=['contract', 'status', 'claim', 'next', 'save', 'validate',
        'revise', 'defer', 'context', 'checkpoint', 'finish', 'release', 'hold', 'exclude', 'resume-review'])
    for option in ('job', 'post', 'input', 'reason', 'query', 'request-id', 'bundle-dir'):
        parser.add_argument('--' + option)
    parser.add_argument('--context-action', choices=['fetch', 'budget', 'search', 'page', 'summary'], default='fetch')
    parser.add_argument('--signal', choices=sorted(disposition.SIGNALS))
    parser.add_argument('--media-index', type=int)
    args = parser.parse_args()
    try:
        run(args)
    except (AssertionError, ValueError, KeyError, TypeError, AttributeError, Conflict, LostLease, QueueError, ClaimBusy, OSError) as exc:
        print(json.dumps({'error': type(exc).__name__, 'message': str(exc) or 'Frozen validation failed'}), file=sys.stderr)
        raise SystemExit(2)


if __name__ == '__main__':
    main()
