"""Atomic metadata sidecars. Accepted answers are never changed by these methods."""
import base64
from datetime import datetime, timezone
import hashlib
import json
import math
import re
import subprocess
import sys
import time
from pipeline_production.common import canonical
from pipeline_production.dispatch import DispatchQueue, AtomicConflict, INDEX_JOB
from pipeline_production.git_queue import Conflict, LostLease, QueueError


def git_failure_category(stderr):
    """Return a fixed category only. Never expose stderr/URLs/credentials."""
    text = stderr.decode('utf-8', 'replace').lower() if isinstance(stderr, bytes) else str(stderr).lower()
    if any(x in text for x in ('429', 'rate limit', 'too many requests')):
        return 'rate_limit'
    if any(x in text for x in ('authentication failed', 'could not read username', 'permission denied',
                               '403', '401', 'repository not found', 'access denied')):
        return 'access'
    if any(x in text for x in ('could not resolve', 'failed to connect', 'connection reset',
                               'connection timed out', 'timed out', 'timeout', 'remote end hung up',
                               'early eof', 'http/2 stream', '502', '503', '504')):
        return 'transient_network'
    return 'other'

DEFER_REASONS = {'approval_required', 'context_record_mismatch', 'needs_quality_review',
                 'image_unavailable', 'source_timestamp_unverifiable'}
META_PATTERN = re.compile(r'(?:deferred-\d+|audit-unaccepted-\d+-[0-9a-f]{64}|context-(?:cache|budget|fetch)-\d+|context-op-\d+-[0-9a-f]{32})\.json')


def cache_value(raw, pid):
    value = json.loads(raw)
    allowed = {'post_id', 'state', 'text', 'code', 'error', 'post_url', 'created_at',
               'author_handle', 'note', 'retrieved_at', 'source_url', 'elapsed_seconds',
               'attempted_at', 'recovered_at'}
    if (not isinstance(value, dict) or set(value) - allowed or value.get('post_id') != pid
            or value.get('state') not in {'available', 'unavailable', 'technical_failure'}
            or (value.get('text') is not None and not isinstance(value['text'], str))):
        raise ValueError('Context cache is not the projected focal-post cache')
    return value


def budget_value(raw):
    value = json.loads(raw)
    if set(value) != {'started_at', 'deadline', 'searches', 'pages', 'queries'}:
        raise ValueError('Context budget shape changed')
    for name in ('started_at', 'deadline'):
        if type(value[name]) not in (int, float) or not math.isfinite(value[name]):
            raise ValueError('Context budget clock is invalid')
    if abs(value['deadline'] - value['started_at'] - 60) > .00001:
        raise ValueError('Context budget deadline changed')
    if (type(value['searches']) is not int or not 0 <= value['searches'] <= 2
            or type(value['pages']) is not int or not 0 <= value['pages'] <= 3
            or len(value['queries']) != value['searches']):
        raise ValueError('Context budget counts are invalid')
    for query in value['queries']:
        if (set(query) != {'query', 'reserved_at'} or not isinstance(query['query'], str)
                or not query['query'].strip() or len(query['query']) > 500
                or not value['started_at'] <= query['reserved_at'] < value['deadline']):
            raise ValueError('Context search reservation is invalid')
    return value


def merge_budget(remote, local):
    if remote is None:
        if local is not None: budget_value(local)
        return local
    if local is None:
        budget_value(remote)
        return remote
    old, new = budget_value(remote), budget_value(local)
    if old['started_at'] != new['started_at'] or old['deadline'] != new['deadline']:
        raise Conflict('Context budget start/deadline cannot be reset')
    if old == new:
        return remote  # Preserve original formatting/bytes as well as its clock.
    if old['searches'] <= new['searches'] and old['pages'] <= new['pages'] and new['queries'][:len(old['queries'])] == old['queries']:
        return local
    if new['searches'] <= old['searches'] and new['pages'] <= old['pages'] and old['queries'][:len(new['queries'])] == new['queries']:
        return remote  # Restore an older local checkpoint; never roll back remote.
    raise Conflict('Context budgets diverged; do not merge independent searches')


def deferred_record(run_id, job_id, post, reason):
    if reason not in DEFER_REASONS:
        raise ValueError('Unknown deferred reason')
    return {'record_type': 'deferred', 'operations_revision': 'ops-r3', 'run_id': run_id,
            'job_id': job_id, 'post_id': post['post_id'], 'reason': reason,
            'image_sha256': sorted({im['sha256'] for im in post['images']})}


def blocked_posts(manifest, metadata):
    hashes, direct = set(), set()
    for name, raw in metadata.items():
        if name.startswith('deferred-'):
            record = json.loads(raw)
            direct.add(record['post_id'])
            hashes.update(record['image_sha256'])
    # A deferred unit is the entire post. If A(x) blocks B(x,y), every
    # attachment of B is also blocked, including y shown through C(y).
    # Production jobs contain at most 50 posts, so this fixed point is bounded.
    blocked = set(direct)
    changed = True
    while changed:
        changed = False
        for post in manifest['posts']:
            attachment_hashes = {im['sha256'] for im in post['images']}
            if post['post_id'] in blocked or attachment_hashes & hashes:
                if post['post_id'] not in blocked or not attachment_hashes <= hashes:
                    blocked.add(post['post_id'])
                    hashes.update(attachment_hashes)
                    changed = True
    return blocked


class OpsQueue(DispatchQueue):
    def __init__(self, remote, run_id, catalog_sha256, jobs, worker_ids, **kwargs):
        self.job_specs = {job['job_id']: job for job in jobs}
        super().__init__(remote, run_id, catalog_sha256, jobs, worker_ids, **kwargs)

    def git(self, *args, data=None, check=True):
        # Retrying reads cannot duplicate a reservation or a result. Writes are
        # never blindly replayed: the existing CAS/lost-ACK logic decides them.
        retry_read = check and args[0] in {'ls-remote', 'fetch'}
        for attempt in range(3 if retry_read else 1):
            try:
                proc = super().git(*args, data=data, check=False)
                if proc.returncode == 0 or not check:
                    return proc
                category = git_failure_category(proc.stderr)
            except subprocess.TimeoutExpired:
                category = 'transient_network'
                proc = None
            if retry_read and category == 'transient_network' and attempt < 2:
                time.sleep(1 + attempt)
                continue
            raise QueueError('Git ' + args[0] + ' failed: ' + category +
                             ' (bounded attempts=' + str(attempt + 1) + ')')

    def __exit__(self, exc_type, exc, traceback):
        # Gate cleanup is not the operation's result. An outage while releasing
        # the short-lived gate must not disguise a committed checkpoint or mask
        # the original error. The gate still expires; never delete/steal it.
        try:
            self.release_claim_gate()
        except (QueueError, Conflict, LostLease):
            print(json.dumps({'warning': 'claim_gate_cleanup_pending',
                              'action': 'preserve_state_wait_for_gate_expiry',
                              'operation_error_preserved': exc is not None}), file=sys.stderr)
        finally:
            self.close()
        return False

    def _owner(self, job_id, token, worker_id):
        head, state = self._owned(job_id, token)
        if state['worker_id'] != worker_id or worker_id not in self.worker_ids:
            raise LostLease('Operational action belongs to another worker')
        return head, state

    def _publish(self, job_id, expected, candidate):
        if job_id in self.jobs and self.claim_gate:
            self._owned(*self.claim_gate)
        return super()._publish(job_id, expected, candidate)

    def _metadata_at(self, head):
        return {name: self.git('show', head + ':' + name).stdout
                for name in self.files(head) if META_PATTERN.fullmatch(name)}

    def read_metadata(self, job_id, token, worker_id):
        head, state = self._owner(job_id, token, worker_id)
        return head, state, self._metadata_at(head)

    def _guard_post(self, job_id, state, pid):
        if not re.fullmatch(r'\d{1,25}', pid) or pid not in self.job_specs[job_id]['post_ids']:
            raise ValueError('Metadata post does not belong to this job')
        if pid in state['completed_posts']:
            raise Conflict('Accepted result cannot be revised or deferred')

    def _guard_unblocked(self, job_id, pid, metadata):
        manifest = self.job_specs[job_id].get('manifest')
        if manifest and pid in blocked_posts(manifest, metadata):
            raise Conflict('Post or an identical attachment is deferred; do not reopen it')

    def _validate_sidecar(self, job_id, name, raw, state):
        if not META_PATTERN.fullmatch(name) or not isinstance(raw, bytes):
            raise ValueError('Only named metadata sidecars may be published')
        value = json.loads(raw)
        if name.startswith('context-cache-'):
            cache_value(raw, name[len('context-cache-'):-5]); return
        if name.startswith('context-budget-'):
            budget_value(raw); return
        pid = value.get('post_id')
        if value.get('run_id') != self.run_id or value.get('job_id') != job_id:
            raise ValueError('Sidecar belongs to another run/job')
        if not isinstance(pid, str) or pid not in self.job_specs[job_id]['post_ids']:
            raise ValueError('Sidecar post is outside the pinned job')
        if name.startswith('deferred-'):
            self._guard_post(job_id, state, pid)
            expected = {'record_type','operations_revision','run_id','job_id','post_id','reason','image_sha256'}
            if (set(value) != expected or value['record_type'] != 'deferred'
                    or value['operations_revision'] not in {'ops-r2', 'ops-r3'} or value['reason'] not in DEFER_REASONS
                    or name != 'deferred-' + pid + '.json'
                    or not value['image_sha256'] or any(not re.fullmatch('[0-9a-f]{64}', h) for h in value['image_sha256'])):
                raise ValueError('Invalid metadata-only deferred record')
            manifest = self.job_specs[job_id].get('manifest')
            if manifest:
                post = next(p for p in manifest['posts'] if p['post_id'] == pid)
                if value['image_sha256'] != sorted({im['sha256'] for im in post['images']}):
                    raise ValueError('Deferred hashes differ from the pinned post')
        elif name.startswith('audit-unaccepted-'):
            self._guard_post(job_id, state, pid)
            if value.get('worker_id') != state['worker_id']:
                raise Conflict('Cannot archive another worker unaccepted answer')
            if (set(value) != {'operations_revision', 'record_type', 'run_id', 'job_id', 'post_id',
                              'worker_id', 'operation', 'reason', 'artifacts'}
                    or value['operations_revision'] not in {'ops-r2', 'ops-r3'}
                    or value['record_type'] != 'unaccepted_history'
                    or value['operation'] not in {'revise', 'defer'}
                    or not isinstance(value['reason'], str) or not 1 <= len(value['reason']) <= 300
                    or name != 'audit-unaccepted-' + pid + '-' + hashlib.sha256(raw).hexdigest() + '.json'
                    or not isinstance(value['artifacts'], dict)
                    or set(value['artifacts']) - {'answer.json', 'draft.json', 'context.json', 'budget.json'}):
                raise ValueError('Invalid unaccepted-history sidecar')
            for artifact in value['artifacts'].values():
                if not isinstance(artifact, dict) or set(artifact) != {'sha256', 'bytes', 'base64'}:
                    raise ValueError('Invalid raw artifact receipt')
                content = base64.b64decode(artifact['base64'], validate=True)
                if (type(artifact['bytes']) is not int or artifact['bytes'] != len(content)
                        or artifact['sha256'] != hashlib.sha256(content).hexdigest()):
                    raise ValueError('History artifact bytes/hash differ')
        elif name.startswith('context-fetch-'):
            if (set(value) != {'run_id', 'job_id', 'post_id', 'record_type', 'attempted_at'}
                    or value['record_type'] != 'context_fetch_attempt'
                    or name != 'context-fetch-' + pid + '.json'
                    or datetime.fromisoformat(value['attempted_at'].replace('Z', '+00:00')).tzinfo is None):
                raise ValueError('Invalid context fetch reservation')
        elif name.startswith('context-op-'):
            request = value.get('request_id')
            action = value.get('action')
            if (set(value) != {'run_id', 'job_id', 'post_id', 'record_type', 'request_id', 'action',
                              'permitted', 'budget_sha256'}
                    or value['record_type'] != 'context_reservation'
                    or action not in {'search', 'page'} or not isinstance(request, str)
                    or not re.fullmatch(action + ('-[12]' if action == 'search' else '-[123]'), request)
                    or type(value['permitted']) is not bool
                    or not re.fullmatch('[0-9a-f]{64}', value['budget_sha256'])
                    or name != 'context-op-' + pid + '-' + hashlib.sha256(request.encode()).hexdigest()[:32] + '.json'):
                raise ValueError('Invalid context tool reservation')

    def _publish_metadata(self, job_id, token, worker_id, build, must_be_unaccepted=()):
        def attempt():
            parent, state, old = self.read_metadata(job_id, token, worker_id)
            for pid in must_be_unaccepted: self._guard_post(job_id, state, pid)
            additions, replace_budget = build(old)
            for name, raw in additions.items():
                self._validate_sidecar(job_id, name, raw, state)
                if name.startswith(('context-fetch-', 'context-op-')) or (
                        name.startswith('audit-unaccepted-') and json.loads(raw)['operation'] == 'revise'):
                    self._guard_unblocked(job_id, json.loads(raw)['post_id'], old)
                if name in old and old[name] != raw:
                    if not (replace_budget and name.startswith('context-budget-')
                            and merge_budget(old[name], raw) == raw):
                        raise Conflict('Existing metadata is immutable or budget would roll back')
            changed = {name: raw for name, raw in additions.items() if old.get(name) != raw}
            if not changed: return parent
            now = int(self.clock())
            state.update(updated_at=now, lease_until=now + self.lease_seconds)
            return self._publish(job_id, parent, self._commit(state, parent, changed))
        return self._retry_mutation(attempt)

    def publish_sidecars(self, job_id, token, additions, worker_id, must_be_unaccepted=()):
        if any(name.startswith(('context-cache-', 'context-budget-')) for name in additions):
            raise ValueError('Context bytes require the dedicated monotonic sync operation')
        return self._publish_metadata(job_id, token, worker_id,
                                      lambda old: (dict(additions), False), must_be_unaccepted)

    def sync_context(self, job_id, token, post_id, cache_bytes, budget_bytes, worker_id):
        if post_id not in self.job_specs[job_id]['post_ids']:
            raise ValueError('Context post is not in this job')
        cache_name, budget_name = 'context-cache-' + post_id + '.json', 'context-budget-' + post_id + '.json'
        selected = {}
        def build(old):
            self._guard_unblocked(job_id, post_id, old)
            cache = old.get(cache_name)
            if cache_bytes is not None:
                cache_value(cache_bytes, post_id)
                if cache is not None and cache != cache_bytes:
                    raise Conflict('Context cache bytes changed; no refetch or replacement')
                cache = cache_bytes
            budget = merge_budget(old.get(budget_name), budget_bytes)
            selected.update(cache=cache, budget=budget)
            return {name: raw for name, raw in ((cache_name, cache), (budget_name, budget)) if raw is not None}, True
        head = self._publish_metadata(job_id, token, worker_id, build)
        return head, selected.get('cache'), selected.get('budget')

    def reserve_context_operation(self, job_id, token, pid, budget_bytes, op_name, op_bytes, worker_id):
        budget_name = 'context-budget-' + pid + '.json'
        def build(old):
            self._guard_unblocked(job_id, pid, old)
            if json.loads(op_bytes).get('budget_sha256') != hashlib.sha256(budget_bytes).hexdigest():
                raise ValueError('Context reservation does not describe these exact budget bytes')
            if op_name in old:
                raise Conflict('Context request ID was already committed; do not execute it again')
            chosen = merge_budget(old.get(budget_name), budget_bytes)
            if chosen != budget_bytes:
                raise Conflict('Context reservation was computed from a stale budget')
            return {budget_name: budget_bytes, op_name: op_bytes}, True
        return self._publish_metadata(job_id, token, worker_id, build, (pid,))

    def checkpoint(self, job_id, token, records, manifest=None, hold=None):
        def attempt():
            head, state = self._owned(job_id, token)
            pinned = self.job_specs[job_id].get('manifest')
            if pinned:
                blocked = blocked_posts(pinned, self._metadata_at(head))
                if (set(records) - set(state['completed_posts'])) & blocked:
                    raise Conflict('Deferred inputs cannot be checkpointed as resolved results')
            # The outer retry repeats the deferred guard after every CAS conflict.
            from pipeline_production.git_queue import GitQueue
            return GitQueue.checkpoint(self, job_id, token, records, manifest, hold)
        return self._retry_mutation(attempt)

    def defer_post(self, job_id, token, post, reason, worker_id):
        raw = canonical(deferred_record(self.run_id, job_id, post, reason))
        return self.publish_sidecars(job_id, token, {'deferred-' + post['post_id'] + '.json': raw},
                                     worker_id, must_be_unaccepted=(post['post_id'],))

    def resume_review(self, job_id, manifest, reason, coordinator_id):
        if coordinator_id != 'ops-coordinator':
            raise ValueError('resume-review is coordinator-only')
        def attempt():
            parent, state = self.read(job_id)
            if not state or state['status'] != 'needs_review':
                raise Conflict('Only needs_review may be resumed')
            original = self.git('show', parent + ':manifest.json').stdout
            if original != canonical(manifest):
                raise Conflict('Pinned review manifest differs')
            pid = state['review']['post_id']; self._guard_post(job_id, state, pid)
            post = next(p for p in manifest['posts'] if p['post_id'] == pid)
            old = self._metadata_at(parent)
            name = 'deferred-' + pid + '.json'
            raw = old.get(name) or canonical(deferred_record(self.run_id, job_id, post, reason))
            self._validate_sidecar(job_id, name, raw, state)
            metadata = dict(old, **{name: raw})
            available = set(self.job_specs[job_id]['post_ids']) - set(state['completed_posts']) - blocked_posts(manifest, metadata)
            if not available:
                raise Conflict('Review job has no remaining ordinary work; do not reopen it repeatedly')
            index_parent, index = self.read_index(); entry = index['entries'][job_id]
            if entry['head'] != parent or entry['status'] != 'needs_review':
                raise AtomicConflict('Review index changed; refresh')
            now = int(self.clock()); state.update(status='available', lease_until=0, retry_after=0, updated_at=now)
            candidate = self._commit(state, parent, {name: raw})
            index['entries'][job_id] = dict(entry, status='available', worker_id=None, dispatch_token=None,
                lease_until=0, retry_after=0, updated_at=now, head=candidate)
            index['attempt'] += 1; index['updated_at'] = now
            index_candidate = self._commit(index, index_parent)
            return self._publish_atomic(job_id, parent, candidate, index_parent, index_candidate)
        return self._retry_mutation(attempt)
