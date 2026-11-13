"""Batch CLI: local next/context/save; shared claim/checkpoint/finish."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import time

from pipeline_production import worker as base, context, disposition
from pipeline_production.common import atomic_write, canonical, digest, read_json
from pipeline_production.git_queue import Conflict, LostLease, QueueError, ClaimBusy
from ops_runtime_r5 import worker as helpers
from ops_runtime_r5.queue import blocked_posts, deferred_record, merge_budget, DEFER_REASONS
from .control import verify_revision, REVISION
from .remote import BatchQueue

ROOT = Path(__file__).resolve().parents[1]


def emit(value):
    print(json.dumps(value, ensure_ascii=False))


def state_path(folder):
    return folder / '.batch' / 'session.json'


def write_session(folder, session):
    atomic_write(state_path(folder), canonical(session))


def metadata_of(session):
    return {name: raw.encode('utf-8') for name, raw in session['metadata'].items()}


def store_metadata(session, name, raw):
    previous = session['metadata'].get(name)
    if previous is not None and previous.encode() != raw:
        if name.startswith('context-budget-'):
            raw = merge_budget(previous.encode(), raw)
        else:
            raise Conflict('Local metadata differs; preserve existing record')
    session['metadata'][name] = raw.decode('utf-8')


def capture_context(folder, manifest, session):
    blocked = blocked_posts(manifest, metadata_of(session))
    for post in manifest['posts']:
        pid = post['post_id']
        if pid in blocked:
            continue
        for prefix, path in zip(('context-cache-', 'context-budget-'), base.context_paths(folder, pid)):
            if path.exists():
                store_metadata(session, prefix + pid + '.json', path.read_bytes())


def restore_context(folder, manifest, session):
    blocked = blocked_posts(manifest, metadata_of(session))
    for name, text in session['metadata'].items():
        if name.startswith('context-cache-'):
            path = base.context_paths(folder, name[len('context-cache-'):-5])[0]
        elif name.startswith('context-budget-'):
            path = base.context_paths(folder, name[len('context-budget-'):-5])[1]
        else:
            continue
        if any(name in {'context-cache-' + pid + '.json', 'context-budget-' + pid + '.json'} for pid in blocked):
            continue
        atomic_write(path, text.encode('utf-8'))


def adopt(queue, folder, config, manifest, lease, worker):
    """Read one remote snapshot; reconcile exact bytes before restoring anything."""
    head, state, metadata = queue.read_metadata(manifest['job_id'], lease['token'], worker)
    prior = read_json(state_path(folder)) if state_path(folder).exists() else {}
    if prior and (prior['lease']['worker_id'] != worker or prior['run_id'] != config['run_id']):
        raise Conflict('Local batch journal belongs to another worker/run')
    session = dict(run_id=config['run_id'], lease=dict(state, head=head),
                   metadata={n: r.decode('utf-8') for n, r in metadata.items()}, accepted={},
                   last_checkpoint_at=time.time(), current_post=prior.get('current_post'))
    for name, text in prior.get('metadata', {}).items():
        store_metadata(session, name, text.encode())
    capture_context(folder, manifest, session)
    restore = {}
    posts = {p['post_id']: p for p in manifest['posts']}
    for pid in state['completed_posts']:
        raw = queue.git('show', head + ':post-' + pid + '.json').stdout
        base.validate_result(json.loads(raw), posts[pid], config, manifest)
        path = folder / 'results' / (pid + '.json')
        if path.exists() and path.read_bytes() != raw:
            raise Conflict('Accepted/local byte mismatch: ' + pid)
        restore[path] = raw
        session['accepted'][pid] = hashlib.sha256(raw).hexdigest()
    # Local-only results are preserved. Never count them as remotely accepted.
    for path in (folder / 'results').glob('*.json'):
        if path.stem not in posts:
            raise Conflict('Local result is outside pinned job')
    for path, raw in restore.items():
        if not path.exists():
            atomic_write(path, raw)
    restore_context(folder, manifest, session)
    write_session(folder, session)
    atomic_write(folder / 'lease.json', canonical(session['lease']))
    return session


def active_rows(folder, manifest, config, session):
    blocked = blocked_posts(manifest, metadata_of(session)) - set(session['accepted'])
    rows = {}
    for path in (folder / 'results').glob('*.json'):
        if path.stem in blocked:
            continue  # Original bytes remain in results and immutable audit history.
        row = read_json(path)
        post = helpers.require_post(manifest, path.stem, set())
        base.validate_result(row, post, config, manifest)
        rows[path.stem] = row
        if path.stem in session['accepted'] and digest(path) != session['accepted'][path.stem]:
            raise Conflict('Accepted local bytes changed')
    if set(session['accepted']) - set(rows):
        raise Conflict('Accepted local copy missing; reconcile restores original bytes')
    return rows


def need_sync(session, rows):
    return (len(set(rows) - set(session['accepted'])) >= 10 or
            time.time() - session['last_checkpoint_at'] >= 600 or
            session['lease']['lease_until'] - time.time() < 300)


def live_lease(session):
    if session['lease']['status'] != 'leased' or session['lease']['lease_until'] <= time.time():
        raise LostLease('Keep local work; claim/checkpoint before opening a new input')


def info(folder, manifest, config, session):
    rows = active_rows(folder, manifest, config, session)
    draft = read_json(folder / 'draft.json') if (folder / 'draft.json').exists() else {}
    return dict(job_id=manifest['job_id'], operations_revision=REVISION,
        remote_accepted_count=len(session['accepted']), remote_head=session['lease']['head'],
        local_pending_ids=sorted(set(rows) - set(session['accepted'])), draft_post_id=draft.get('post_id'),
        current_post_id=session.get('current_post'), checkpoint_due=need_sync(session, rows),
        lease_seconds_remaining=max(0, int(session['lease']['lease_until'] - time.time())))


def context_local(args, folder, manifest, config, session):
    pid, action = args.post, args.context_action
    if action == 'summary':
        return context.report(base.context_paths(folder, pid)[1])
    live_lease(session)
    if pid in session['accepted']:
        raise Conflict('Accepted input must not be researched again')
    cache, ledger = base.context_paths(folder, pid)
    if action == 'fetch':
        if cache.exists():
            return read_json(cache)
        name = 'context-fetch-' + pid + '.json'
        if name in session['metadata']:
            marker = json.loads(session['metadata'][name])
            result = dict(post_id=pid, state='technical_failure', text=None,
                          error='prior_fetch_interrupted', attempted_at=marker['attempted_at'])
            atomic_write(cache, canonical(result))
        else:
            marker = dict(run_id=config['run_id'], job_id=manifest['job_id'], post_id=pid,
                          record_type='context_fetch_attempt', attempted_at=helpers.utcnow())
            store_metadata(session, name, canonical(marker))
            write_session(folder, session)  # durable before the external request
            result = context.fetch(pid, cache)
        store_metadata(session, 'context-cache-' + pid + '.json', cache.read_bytes())
        write_session(folder, session)
        return result
    if action not in {'budget', 'search', 'page'}:
        raise ValueError('Unknown context action')
    request = getattr(args, 'request_id', None)
    name = None
    if action in {'search', 'page'}:
        if not isinstance(request, str) or not re.fullmatch(action + ('-[12]' if action == 'search' else '-[123]'), request):
            raise ValueError('Use fixed search-1/search-2 or page-1..page-3 request IDs')
        name = 'context-op-' + pid + '-' + hashlib.sha256(request.encode()).hexdigest()[:32] + '.json'
        count_key = 'searches' if action == 'search' else 'pages'
        old = read_json(ledger) if ledger.exists() else {count_key: 0}
        ordinal = int(request.rsplit('-', 1)[1])
        if name in session['metadata'] or ordinal <= old[count_key]:
            return dict(context.report(ledger), permitted=False, replayed=True, request_id=request)
        if ordinal != old[count_key] + 1:
            raise ValueError('Use context request IDs in order')
    result = context.budget(ledger, action, query=getattr(args, 'query', None))
    raw = ledger.read_bytes()
    store_metadata(session, 'context-budget-' + pid + '.json', raw)
    if name:
        operation = dict(run_id=config['run_id'], job_id=manifest['job_id'], post_id=pid,
            record_type='context_reservation', request_id=request, action=action,
            permitted=result['permitted'], budget_sha256=hashlib.sha256(raw).hexdigest())
        store_metadata(session, name, canonical(operation))
    write_session(folder, session)  # no permission returned before durable local journal
    return dict(result, request_id=request, replayed=False)


def local(args, folder, manifest, config, session):
    command, worker = args.command, args.worker
    metadata = metadata_of(session)
    blocked = blocked_posts(manifest, metadata)
    if command == 'inspect':
        return info(folder, manifest, config, session)
    rows = active_rows(folder, manifest, config, session) if command not in {'defer', 'revise', 'exclude'} else {
        p.stem: read_json(p) for p in (folder / 'results').glob('*.json')}
    if command == 'next':
        live_lease(session)
        for post in manifest['posts']:
            pid = post['post_id']
            if pid in rows or pid in blocked:
                continue
            base.check_post_files(folder, post, base.load_policy(config, ROOT))
            refused = helpers.refusal_hashes(manifest, rows)
            duplicate = next((im for im in post['images'] if im['sha256'] in refused), None)
            if duplicate:
                return dict(status='known_refusal_requires_exclusion', post_id=pid,
                            media_index=duplicate['media_index'], signal=refused[duplicate['sha256']])
            path = folder / 'draft.json'
            draft = read_json(path) if path.exists() else None
            resumed = bool(draft and draft.get('post_id') == pid and
                draft.get('provenance') == base.provenance(config, manifest) and
                draft.get('execution', {}).get('worker_id') == worker)
            if not resumed:
                if draft:
                    raw = path.read_bytes()
                    atomic_write(folder / '.batch' / 'draft-history' / (hashlib.sha256(raw).hexdigest() + '.json'), raw)
                atomic_write(path, canonical(base.schema_for(config).template(post,
                    base.provenance(config, manifest), worker_id=worker)))
            session['current_post'] = pid
            write_session(folder, session)
            return dict(post_id=pid, images=[str(folder / im['path']) for im in post['images']],
                draft=str(path), resumed_draft=resumed, checkpoint_due=need_sync(session, rows),
                lease_seconds_remaining=max(0, int(session['lease']['lease_until'] - time.time())))
        return dict(status='local_batch_complete', next='finish', deferred_unresolved=len(blocked - set(rows)))
    if command in {'context', 'defer', 'exclude', 'revise'}:
        post = helpers.require_post(manifest, args.post, set() if command in {'defer', 'exclude'} else blocked)
        if command == 'defer' and args.post in blocked:
            return dict(status='deferred', post_id=args.post, already_deferred=True, remote_accepted=False)
        if command not in {'defer', 'exclude'}:
            helpers.guard_refusal(post, rows, manifest)
    if command == 'context':
        return context_local(args, folder, manifest, config, session)
    if command == 'exclude':
        pid = args.post
        if pid in session['accepted'] or (pid in rows and not disposition.is_exclusion(rows[pid])):
            raise Conflict('Existing label cannot be replaced by exclusion')
        path = folder / 'results' / (pid + '.json')
        row = rows.get(pid) or disposition.create(post, base.provenance(config, manifest), worker,
                                                 args.signal, args.media_index)
        base.validate_result(row, post, config, manifest)
        atomic_write(path, canonical(row))
        return dict(excluded_post=pid, temporary=True, saved_locally=True, remote_accepted=False, next='next')
    if command == 'defer':
        if args.reason not in DEFER_REASONS or args.post in session['accepted']:
            raise Conflict('Invalid defer reason or accepted result')
        name = 'deferred-' + args.post + '.json'
        addition = canonical(deferred_record(config['run_id'], manifest['job_id'], post, args.reason))
        affected = blocked_posts(manifest, dict(metadata, **{name: addition})) - blocked - set(session['accepted'])
        for pid in affected:
            row = rows.get(pid)
            if row and (disposition.is_exclusion(row) or row.get('execution', {}).get('worker_id') != worker):
                raise Conflict('Cannot defer another worker or policy exclusion result')
            history_name, raw = helpers.history_record(folder, config, manifest, pid, worker, 'defer', args.reason)
            store_metadata(session, history_name, raw)
        store_metadata(session, name, addition)
        capture_context(folder, manifest, session)
        write_session(folder, session)
        return dict(status='deferred', post_id=args.post, saved_locally=True, remote_accepted=False, next='next')
    if command in {'save', 'validate', 'revise'}:
        source = Path(args.input) if args.input else folder / 'draft.json'
        row = read_json(source)
        post = helpers.require_post(manifest, row.get('post_id'), blocked)
        pid = post['post_id']
        if disposition.is_exclusion(row):
            raise ValueError('Use exclude for actual policy refusal')
        helpers.guard_refusal(post, rows, manifest)
        if row['execution']['worker_id'] != worker:
            raise Conflict('Draft belongs to another worker')
        raw = canonical(row)
        if pid in session['accepted']:
            if hashlib.sha256(raw).hexdigest() != session['accepted'][pid]:
                raise Conflict('Accepted answers are immutable')
            return dict(already_accepted=pid, remote_accepted=True)
        if row['execution']['finished_at'] is None:
            row['execution']['finished_at'] = helpers.utcnow()
        base.validate_draft(row, post, config, manifest, folder)
        capture_context(folder, manifest, session)
        if command == 'validate':
            return dict(valid=True, post_id=pid, saved=False)
        path = folder / 'results' / (pid + '.json')
        if command == 'revise':
            if args.post != pid or not path.exists():
                raise ValueError('Revise requires own existing unaccepted result for this post')
            old = read_json(path)
            if old.get('execution', {}).get('worker_id') != worker or disposition.is_exclusion(old):
                raise Conflict('Cannot revise another worker or exclusion')
            if old.get('provenance') != base.provenance(config, manifest) or old.get('post_id') != pid:
                raise Conflict('Original answer belongs to another run/post')
            name, raw = helpers.history_record(folder, config, manifest, pid, worker, 'revise', args.reason)
            store_metadata(session, name, raw)
        elif path.exists() and path.read_bytes() != canonical(row):
            raise Conflict('Local result differs; use revise')
        write_session(folder, session)
        atomic_write(path, canonical(row))
        atomic_write(source, canonical(row))
        return dict(saved_locally=pid, remote_accepted=False, checkpoint_due=need_sync(session, dict(rows, **{pid: row})))
    raise ValueError('Unknown local command')


def run(args):
    assert __debug__, 'Do not disable frozen validation with Python -O'
    verified = verify_revision(ROOT, args.config, args.worker, require_enabled=args.command != 'contract')
    config, catalog = verified['config'], verified['catalog']
    if args.command == 'contract':
        emit(base.schema_for(config).definition()); return
    base.require_launch(config, catalog, ROOT)
    jobs = {j['job_id']: j for j in catalog['jobs'] if j['job_id'] in config['job_ids']}
    runtime = ROOT / '.runtime' / config['run_id']
    with helpers.local_lock(runtime, args.worker):
        if args.command in {'claim', 'status', 'checkpoint', 'finish', 'reconcile'}:
            with BatchQueue(config['remote'], config['run_id'], config['catalog_sha256'],
                            list(jobs.values()), config['worker_ids']) as queue:
                if args.command == 'status':
                    emit(queue.status()); return
                if args.command == 'claim':
                    result = queue.claim(args.worker)
                    if 'lease' not in result:
                        emit(result); return
                    lease = result['lease']; job = jobs[lease['job_id']]
                    folder = runtime / job['job_id']
                    manifest = base.prepare_job(catalog, job, folder,
                        read_json(base.pinned_path(config, 'assets_path', 'data/assets.json')),
                        base.load_policy(config, ROOT), bundle_dir=args.bundle_dir)
                    session = adopt(queue, folder, config, manifest, lease, args.worker)
                    emit(dict(info(folder, manifest, config, session), status=result['status'], folder=str(folder))); return
                folder, manifest, session = load_local(args, config, jobs, runtime)
                if args.command == 'reconcile':
                    session = adopt(queue, folder, config, manifest, session['lease'], args.worker)
                    emit(info(folder, manifest, config, session)); return
                capture_context(folder, manifest, session)
                write_session(folder, session)
                rows = active_rows(folder, manifest, config, session)
                for pid, row in rows.items():
                    if pid not in session['accepted']:
                        post = helpers.require_post(manifest, pid, set())
                        base.validate_draft(row, post, config, manifest, folder)
                        if not disposition.is_exclusion(row) and row['execution']['worker_id'] != args.worker:
                            raise Conflict('Cannot publish another worker unfinished result')
                head, state, metadata = queue.commit_batch(args.job, session['lease']['token'], args.worker,
                    manifest, rows, metadata_of(session), finish=args.command == 'finish')
                session.update(lease=dict(state, head=head), metadata={n: r.decode() for n, r in metadata.items()},
                    accepted={pid: hashlib.sha256(canonical(row)).hexdigest() for pid, row in rows.items()},
                    last_checkpoint_at=time.time())
                restore_context(folder, manifest, session)
                write_session(folder, session)
                atomic_write(folder / 'lease.json', canonical(session['lease']))
                emit(dict(info(folder, manifest, config, session), status=state['status'])); return
        folder, manifest, session = load_local(args, config, jobs, runtime)
        emit(local(args, folder, manifest, config, session))


def load_local(args, config, jobs, runtime):
    if args.job not in jobs:
        raise ValueError('Job is outside pinned run')
    folder = runtime / args.job
    if digest(folder / 'manifest.json') != jobs[args.job]['manifest_sha256']:
        raise ValueError('Pinned job manifest differs')
    manifest = read_json(folder / 'manifest.json')
    base.check_manifest(manifest, base.load_policy(config, ROOT))
    session = read_json(state_path(folder))
    if (session['run_id'] != config['run_id'] or session['lease']['job_id'] != args.job or
            session['lease']['worker_id'] != args.worker):
        raise LostLease('Local journal is for another run/job/worker')
    return folder, manifest, session


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config', required=True); p.add_argument('--worker', required=True)
    p.add_argument('command', choices=['contract', 'status', 'claim', 'next', 'inspect', 'save', 'validate',
        'revise', 'defer', 'exclude', 'context', 'checkpoint', 'finish', 'reconcile'])
    for option in ('job', 'post', 'input', 'reason', 'query', 'request-id', 'bundle-dir'):
        p.add_argument('--' + option)
    p.add_argument('--context-action', choices=['fetch', 'budget', 'search', 'page', 'summary'], default='fetch')
    p.add_argument('--signal', choices=sorted(disposition.SIGNALS)); p.add_argument('--media-index', type=int)
    try:
        run(p.parse_args())
    except (AssertionError, ValueError, KeyError, TypeError, Conflict, LostLease, QueueError, ClaimBusy, OSError) as exc:
        print(json.dumps({'error': type(exc).__name__, 'message': str(exc) or 'Frozen validation failed'}), file=sys.stderr)
        raise SystemExit(2)


if __name__ == '__main__':
    main()
