"""One fenced job/index transaction publishes all locally durable work."""
import hashlib
import json
import random
import time

from pipeline_production.common import canonical
from pipeline_production.dispatch import GRACE_SECONDS
from pipeline_production.git_queue import GitQueue, Conflict, ClaimBusy, QueueError, LostLease
from ops_runtime_r5.queue import OpsQueue, blocked_posts, merge_budget


class BatchQueue(OpsQueue):
    def claim(self, worker_id):
        """Expired work stays with its owner; unseen local journals are not stolen."""
        if worker_id not in self.worker_ids:
            raise ValueError('Worker is outside pinned scope')
        self.acquire_claim_gate(worker_id)
        try:
            for _ in range(48):
                _, index = self.read_index()
                own = [(j, e) for j, e in index['entries'].items()
                       if e['status'] == 'assigned' and e['worker_id'] == worker_id]
                now = self.clock()
                if own:
                    jid, entry = own[0]
                    head, state = self.read(jid)
                    if head != entry['head']:
                        continue
                    if entry['lease_until'] > now:
                        return {'status': 'active_job_exists', 'lease': dict(state, head=head)}
                    if entry['lease_until'] + GRACE_SECONDS > now:
                        return {'status': 'retry_after', 'retry_at': entry['lease_until'] + GRACE_SECONDS,
                                'job_id': jid, 'reason': 'expired_lease_grace'}
                    candidates = [jid]
                else:
                    candidates = [j for j, e in index['entries'].items()
                                  if e['status'] in {'pending', 'available'} and e['retry_after'] <= now]
                    random.Random(self.run_id + worker_id).shuffle(candidates)
                if not candidates:
                    return self._summary(index)
                try:
                    lease = GitQueue.reserve(self, candidates[0], worker_id)
                    if lease:
                        return {'status': 'claimed', 'lease': lease}
                except Conflict:
                    time.sleep(random.uniform(.03, .15))
            raise ClaimBusy('Dispatch busy; retain local work and retry later')
        finally:
            self.release_claim_gate()

    def commit_batch(self, job, token, worker, manifest, rows, metadata, finish=False):
        """Validate everything, then atomically publish rows, sidecars and index.

        Retain the r5 wire format for sidecars and all existing receipt bytes.
        No claim gate is needed here: local OS lock plus job/index CAS fence it.
        """
        def attempt():
            try:
                parent, state, old = self.read_metadata(job, token, worker)
            except LostLease:
                parent, state = self.read(job)
                if (not state or state['status'] not in {'completed', 'needs_review'} or
                        state['worker_id'] != worker or state['token'] != token):
                    raise
                old = self._metadata_at(parent)
                for pid, row in rows.items():
                    if pid not in state['completed_posts'] or self.git('show', parent + ':post-' + pid + '.json').stdout != canonical(row):
                        raise Conflict('Terminal result differs from pending work')
                for name, raw in metadata.items():
                    if old.get(name) != raw:
                        raise Conflict('Terminal metadata differs from pending work')
                return parent, state, old
            additions = {}
            for name, raw in metadata.items():
                if old.get(name) == raw:
                    continue
                self._validate_sidecar(job, name, raw, state)
                if name in old:
                    if name.startswith('context-budget-'):
                        raw = merge_budget(old[name], raw)
                    else:
                        raise Conflict('Shared metadata differs; preserve both versions')
                additions[name] = raw
            merged = dict(old, **additions)
            blocked = blocked_posts(manifest, merged)
            if (set(rows) - set(state['completed_posts'])) & blocked:
                raise Conflict('Deferred post cannot become a completed label')
            existing = self.files(parent)
            if 'manifest.json' in existing and self.git('show', parent + ':manifest.json').stdout != canonical(manifest):
                raise Conflict('Pinned manifest changed')
            additions['manifest.json'] = canonical(manifest)
            for pid, row in rows.items():
                if pid not in self.job_specs[job]['post_ids'] or row.get('post_id') != pid:
                    raise ValueError('Result belongs to another post/job')
                name, raw = 'post-' + pid + '.json', canonical(row)
                if name in existing and self.git('show', parent + ':' + name).stdout != raw:
                    raise Conflict('Accepted results are immutable')
                additions[name] = raw
            done = set(state['completed_posts']) | set(rows)
            now = int(self.clock())
            state.update(completed_posts=sorted(done), updated_at=now, lease_until=now + self.lease_seconds)
            if finish:
                missing = set(self.job_specs[job]['post_ids']) - done
                if missing - blocked:
                    raise QueueError('Ordinary posts remain unfinished')
                if missing:
                    state.update(status='needs_review', lease_until=0,
                                 review={'post_id': sorted(missing)[0], 'reason': 'input_requires_review'})
                else:
                    payload = b''.join(additions.get('post-' + pid + '.json') or
                        self.git('show', parent + ':post-' + pid + '.json').stdout for pid in sorted(done))
                    additions['labels.jsonl'] = payload
                    state.update(status='completed', lease_until=0, result_count=len(done),
                                 result_sha256=hashlib.sha256(payload).hexdigest())
            head = self._publish(job, parent, self._commit(state, parent, additions))
            return head, state, merged
        return self._retry_mutation(attempt)
