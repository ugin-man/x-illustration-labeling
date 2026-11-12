"""Atomic Git dispatch index + per-job commits, with no coordinator hot path.

Every research-job mutation publishes its new job commit AND the matching small
index commit using one `git push --atomic`. Both are children of exactly the
observed heads; ordinary non-fast-forward rejection is the CAS. No force push,
two-phase intent, orphan reservation, or fallback to non-atomic pushes is used.
The index stores exact committed job heads, leases and counts, so ordinary claims
and read-only status never scan completed job branches.
"""
import json
import random
import time

from .git_queue import GitQueue, ClaimBusy, Conflict, QueueError, safe_id


INDEX_JOB = 'dispatch-index'
VERSION = 'dispatch-v1'
GRACE_SECONDS = 120


class AtomicConflict(Conflict):
    """A rejected atomic pair can be rebuilt from fresh heads without data loss."""


class DispatchQueue(GitQueue):
    def __init__(self, remote, run_id, catalog_sha256, jobs, worker_ids,
                 lease_seconds=3600, clock=time.time):
        super().__init__(remote, run_id, catalog_sha256, lease_seconds, clock)
        self.jobs = {j['job_id']: len(j['post_ids']) for j in jobs}
        self.worker_ids = tuple(worker_ids)
        if not self.jobs or len(set(self.worker_ids)) != len(self.worker_ids):
            raise ValueError('Invalid dispatcher scope')
        for jid in self.jobs:
            safe_id(jid)
            if jid == INDEX_JOB or jid.startswith('claim-gate-'):
                raise ValueError('Research job uses a reserved queue identifier')

    def acquire_claim_gate(self, worker_id):
        # Startup contention can take longer than the pilot's 60-second gate.
        jid = 'claim-gate-' + safe_id(worker_id)
        previous = self.lease_seconds
        try:
            self.lease_seconds = 300
            lease = GitQueue.reserve(self, jid, worker_id)
        except Conflict as exc:
            raise ClaimBusy('Concurrent claim for this worker identity') from exc
        finally:
            self.lease_seconds = previous
        if lease is None:
            raise ClaimBusy('Concurrent claim for this worker identity')
        self.claim_gate = (jid, lease['token'])
        return lease

    def _empty_index(self):
        return dict(run_id=self.run_id, job_id=INDEX_JOB,
                    catalog_sha256=self.catalog_sha256, queue_version=VERSION,
                    status='active', attempt=0, updated_at=int(self.clock()),
                    worker_ids=list(self.worker_ids), entries={jid: {
                        'status': 'pending', 'post_count': count,
                        'completed_posts': 0, 'worker_id': None,
                        'dispatch_token': None, 'lease_until': 0,
                        'retry_after': 0, 'updated_at': 0, 'head': None,
                    } for jid, count in self.jobs.items()})

    def read_index(self):
        head, state = GitQueue.read(self, INDEX_JOB)
        state = state or self._empty_index()
        if (state.get('queue_version') != VERSION
                or state.get('worker_ids') != list(self.worker_ids)
                or set(state.get('entries', {})) != set(self.jobs)):
            raise QueueError('Dispatch index belongs to a different fixed scope')
        active_workers = []
        for jid, entry in state['entries'].items():
            if entry.get('post_count') != self.jobs[jid]:
                raise QueueError('Dispatch post count changed')
            if entry['status'] not in {'pending', 'assigned', 'available', 'completed', 'needs_review'}:
                raise QueueError('Invalid dispatch status')
            if not 0 <= entry['completed_posts'] <= entry['post_count']:
                raise QueueError('Invalid dispatch progress count')
            if entry['status'] == 'assigned':
                if entry.get('worker_id') not in self.worker_ids or not entry.get('dispatch_token'):
                    raise QueueError('Invalid dispatch assignment')
                active_workers.append(entry['worker_id'])
        if len(set(active_workers)) != len(active_workers):
            raise QueueError('A worker has multiple dispatch assignments')
        return head, state

    def _publish_atomic(self, job_id, expected_job, candidate_job,
                        expected_index, candidate_index):
        # Explicit --atomic is mandatory. Unsupported servers fail closed; never
        # split this into separate pushes or use --force/--force-with-lease.
        proc = self.git('push', '--atomic', '--porcelain', 'origin',
                        f'{candidate_index}:{self.ref(INDEX_JOB)}',
                        f'{candidate_job}:{self.ref(job_id)}', check=False)
        if proc.returncode == 0:
            return candidate_job
        raw = self.git('ls-remote', '--heads', 'origin', self.ref(INDEX_JOB), self.ref(job_id)).stdout.decode()
        observed = {line.split()[1]: line.split()[0] for line in raw.splitlines() if line}
        # Lost ACK: another worker may already have advanced the index, but this
        # exact job head proves the atomic pair was accepted. No partial pair is
        # possible on an atomic-capable server.
        if observed.get(self.ref(job_id)) == candidate_job:
            return candidate_job
        if (observed.get(self.ref(INDEX_JOB)) != expected_index
                or observed.get(self.ref(job_id)) != expected_job):
            raise AtomicConflict('Atomic dispatch transaction lost a CAS race; refresh and retry')
        raise QueueError('Atomic Git transaction was not accepted; check network/access and server atomic-push support')

    def _publish(self, job_id, expected, candidate):
        if job_id not in self.jobs:
            if job_id == INDEX_JOB:
                raise QueueError('Index may only change in an atomic research-job transaction')
            return super()._publish(job_id, expected, candidate)
        parent, index = self.read_index()
        entry = index['entries'][job_id]
        state = json.loads(self.git('show', candidate + ':state.json').stdout)
        owner = state['worker_id']
        if owner not in self.worker_ids or entry['head'] != expected:
            raise AtomicConflict('Job head/worker differs from the atomic dispatch snapshot')
        new_reservation = state['status'] == 'leased' and state['token'] != entry['dispatch_token']
        if new_reservation:
            if entry['status'] in {'completed', 'needs_review'}:
                raise Conflict('Terminal job cannot be reserved')
            if entry['status'] == 'assigned' and entry['lease_until'] + GRACE_SECONDS > self.clock():
                raise Conflict('Job is still reserved')
            if entry['retry_after'] > self.clock():
                raise Conflict('Job retry delay has not elapsed')
            if any(jid != job_id and e['status'] == 'assigned' and e['worker_id'] == owner
                   for jid, e in index['entries'].items()):
                raise Conflict('Worker already has another assignment; resume it')
        elif (entry['status'] != 'assigned' or entry['dispatch_token'] != state['token']
              or entry['worker_id'] != owner or entry['lease_until'] <= self.clock()):
            raise Conflict('Reservation is expired or fenced in the dispatch index')
        assigned = state['status'] == 'leased'
        index['entries'][job_id] = dict(entry,
            status='assigned' if assigned else state['status'],
            worker_id=owner if assigned else None,
            dispatch_token=state['token'] if assigned else None,
            lease_until=state['lease_until'], retry_after=state.get('retry_after', 0),
            completed_posts=len(state['completed_posts']), head=candidate,
            updated_at=state['updated_at'])
        index['attempt'] += 1
        index['updated_at'] = int(self.clock())
        candidate_index = self._commit(index, parent)
        return self._publish_atomic(job_id, expected, candidate, parent, candidate_index)

    def _retry_mutation(self, method, *args, **kwargs):
        for attempt in range(24):
            try:
                return method(*args, **kwargs)
            except AtomicConflict:
                # Reread the job/token and index. LostLease, immutable-answer
                # conflicts and validation errors are deliberately not retried.
                if attempt == 23:
                    raise
                time.sleep(random.uniform(.03, .15))

    def checkpoint(self, *args, **kwargs):
        return self._retry_mutation(super().checkpoint, *args, **kwargs)

    def finish(self, *args, **kwargs):
        return self._retry_mutation(super().finish, *args, **kwargs)

    def release(self, *args, **kwargs):
        return self._retry_mutation(super().release, *args, **kwargs)

    def claim(self, worker_id):
        if worker_id not in self.worker_ids:
            raise ValueError('Only pinned production worker identities may claim')
        self.acquire_claim_gate(worker_id)
        try:
            for attempt in range(48):
                _, index = self.read_index()
                own = [(jid, e) for jid, e in index['entries'].items()
                       if e['status'] == 'assigned' and e['worker_id'] == worker_id]
                now = self.clock()
                if own:
                    jid, entry = own[0]
                    head, state = GitQueue.read(self, jid)
                    if head != entry['head']:
                        continue  # Concurrent checkpoint/finish; get a fresh pair.
                    if entry['lease_until'] > now:
                        return {'status': 'active_job_exists', 'lease': dict(state, head=head)}
                    if entry['lease_until'] + GRACE_SECONDS > now:
                        return {'status': 'retry_after', 'retry_at': entry['lease_until'] + GRACE_SECONDS,
                                'job_id': jid, 'reason': 'expired_lease_grace'}
                    candidates = [jid]  # Finish/reacquire own expired job before another.
                else:
                    candidates = [jid for jid, e in index['entries'].items()
                        if (e['status'] in {'pending', 'available'} and e['retry_after'] <= now)
                        or (e['status'] == 'assigned' and e['lease_until'] + GRACE_SECONDS <= now)]
                    random.Random(self.run_id + worker_id).shuffle(candidates)
                if not candidates:
                    return self._summary(index)
                try:
                    lease = GitQueue.reserve(self, candidates[0], worker_id)
                    if lease:
                        return {'status': 'claimed', 'lease': lease}
                except Conflict:
                    time.sleep(random.uniform(.03, .15))
            raise ClaimBusy('Dispatch index remained busy; retry with bounded backoff')
        finally:
            self.release_claim_gate()

    def _summary(self, state):
        now = int(self.clock())
        counts = {name: 0 for name in ('pending', 'available', 'leased', 'expired',
                                      'retry_wait', 'completed', 'needs_review')}
        workers, retries, public_jobs = [], [], []
        completed_posts = unresolved_posts = 0
        for jid, entry in state['entries'].items():
            status = entry['status']
            if status == 'assigned':
                status = 'expired' if entry['lease_until'] + GRACE_SECONDS <= now else 'leased'
                workers.append({'worker_id': entry['worker_id'], 'job_id': jid,
                    'status': status, 'lease_until': entry['lease_until'],
                    'updated_at': entry['updated_at'], 'head': entry['head'],
                    'completed_posts': entry['completed_posts'], 'post_count': entry['post_count']})
            elif status == 'available' and entry['retry_after'] > now:
                status = 'retry_wait'
                retries.append(entry['retry_after'])
            counts[status] += 1
            completed_posts += entry['completed_posts']
            unresolved_posts += entry['post_count'] - entry['completed_posts']
            public_jobs.append({'job_id': jid, 'status': status, 'head': entry['head'],
                'updated_at': entry['updated_at'], 'post_count': entry['post_count'],
                'completed_posts': entry['completed_posts']})
        if counts['completed'] == len(self.jobs):
            status = 'all_done'
        elif counts['pending'] or counts['available'] or counts['expired']:
            status = 'available'
        elif retries:
            status = 'retry_after'
        elif workers:
            status = 'all_leased'
        else:
            status = 'needs_review'
        return {'status': status, 'run_id': self.run_id, 'queue_version': VERSION,
            'observed_at': now, 'counts': counts, 'workers': workers,
            'checkpointed_posts': completed_posts, 'unresolved_posts': unresolved_posts,
            'total_posts': sum(self.jobs.values()), 'retry_at': min(retries) if retries else None,
            'jobs': public_jobs}

    def status(self):
        # One read-only index snapshot: no gates, writes, lease extension, job scan,
        # or fencing tokens in returned metadata. Paired job commits are atomic.
        _, state = self.read_index()
        return self._summary(state)
