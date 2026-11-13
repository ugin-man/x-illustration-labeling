"""Exact-commit push recovery, synthetic responses only."""
import json
import subprocess
import unittest
from unittest.mock import Mock, patch

from ops_runtime_r4.queue import OpsQueue
from pipeline_production.dispatch import AtomicConflict
from pipeline_production.git_queue import Conflict, LostLease, QueueError, ClaimBusy


class PushRecoveryTests(unittest.TestCase):
    def setup_queue(self, responses, observations, atomic=False):
        q = OpsQueue.__new__(OpsQueue)
        q.run_id = 'synthetic'
        q.claim_gate = None
        q.clock = lambda: 100
        job = 'job-1' if atomic else 'claim-gate-worker-1'
        ref = q.ref(job)
        expected, candidates = {ref: 'old'}, {ref: 'new'}
        if atomic:
            expected[q.ref('dispatch-index')] = 'index-old'
            candidates[q.ref('dispatch-index')] = 'index-new'
        pushes, reads = iter(responses), iter(observations)
        def git(*args, **kwargs):
            if args[0] == 'show':
                return subprocess.CompletedProcess(args, 0, json.dumps({'status':'leased','lease_until':1000}).encode(), b'')
            value = next(pushes) if args[0] == 'push' else next(reads)
            if isinstance(value, Exception):
                raise value
            if args[0] == 'ls-remote':
                return subprocess.CompletedProcess(args, 0, ''.join(v+'\t'+k+'\n' for k,v in value.items()).encode(), b'')
            return value
        q.git = Mock(side_effect=git)
        return q, job, expected, candidates

    def response(self, code=1, error=b'HTTP 503 upstream unavailable'):
        return subprocess.CompletedProcess(['git'], code, b'', error)

    def publish(self, q, job, old, new, atomic=False):
        with patch('ops_runtime_r4.queue.time.sleep'):
            return q._publish_checked(job, old, new, atomic=atomic)

    def test_transient_push_replays_exact_commit_only_after_unchanged_refs(self):
        for atomic in (False, True):
            with self.subTest(atomic=atomic):
                q,j,old,new=self.setup_queue([self.response(),self.response(0)],[],atomic)
                q,j,old,new=self.setup_queue([self.response(),self.response(0)],[old],atomic)
                self.assertEqual(self.publish(q,j,old,new,atomic), 'new')
                calls=[c for c in q.git.call_args_list if c.args[0]=='push']
                self.assertEqual(len(calls),2)
                self.assertEqual(calls[0],calls[1])
                self.assertNotIn('--force',calls[0].args)
                self.assertEqual('--atomic' in calls[0].args,atomic)

    def test_lost_ack_is_accepted_without_second_push(self):
        for atomic in (False,True):
            q,j,old,new=self.setup_queue([self.response()],[],atomic)
            seen=dict(new)
            if atomic:seen[q.ref('dispatch-index')]='later-index'
            q,j,old,new=self.setup_queue([self.response()],[seen],atomic)
            self.assertEqual(self.publish(q,j,old,new,atomic),'new')
            self.assertEqual(sum(c.args[0]=='push' for c in q.git.call_args_list),1)

    def test_changed_refs_are_never_replayed(self):
        for atomic,error in ((False,Conflict),(True,AtomicConflict)):
            q,j,old,new=self.setup_queue([self.response()],[],atomic)
            seen=dict(old);seen[q.ref(j)]='someone-else'
            q,j,old,new=self.setup_queue([self.response()],[seen],atomic)
            with self.assertRaises(error):self.publish(q,j,old,new,atomic)
            self.assertEqual(sum(c.args[0]=='push' for c in q.git.call_args_list),1)

    def test_auth_rate_limit_and_unknown_stop_without_leaking_output(self):
        for raw,category in ((b'HTTP 403 secret-token','access'),(b'HTTP 429 private-url','rate_limit'),(b'sensitive unrecognized failure','other')):
            q,j,old,new=self.setup_queue([self.response(error=raw)],[])
            q,j,old,new=self.setup_queue([self.response(error=raw)],[old])
            with self.assertRaisesRegex(QueueError,category) as caught:self.publish(q,j,old,new)
            self.assertNotIn(raw.decode(),str(caught.exception))
            self.assertEqual(sum(c.args[0]=='push' for c in q.git.call_args_list),1)

    def test_push_timeout_still_reconciles_lost_ack(self):
        q,j,old,new=self.setup_queue([],[])
        q,j,old,new=self.setup_queue([QueueError('Git push failed: transient_network')],[new])
        self.assertEqual(self.publish(q,j,old,new),'new')

    def test_failed_observation_does_not_replay_uncertain_push(self):
        q,j,old,new=self.setup_queue([self.response()],[QueueError('read failed')])
        with self.assertRaisesRegex(QueueError,'acceptance_indeterminate'):self.publish(q,j,old,new)
        self.assertEqual(sum(c.args[0]=='push' for c in q.git.call_args_list),1)

    def test_transient_push_is_bounded_at_ten(self):
        q,j,old,new=self.setup_queue([],[])
        q,j,old,new=self.setup_queue([self.response()]*10,[old]*10)
        with self.assertRaisesRegex(QueueError,'bounded_attempts=10'):self.publish(q,j,old,new)
        self.assertEqual(sum(c.args[0]=='push' for c in q.git.call_args_list),10)

    def test_longer_transient_outage_recovers_without_rebuilding_commit(self):
        q,j,old,new=self.setup_queue([],[])
        q,j,old,new=self.setup_queue([self.response()]*4+[self.response(0)],[old]*4)
        self.assertEqual(self.publish(q,j,old,new),'new')
        pushes=[c for c in q.git.call_args_list if c.args[0]=='push']
        self.assertEqual(len(pushes),5)
        self.assertTrue(all(c==pushes[0] for c in pushes))

    def test_read_recovers_after_several_transient_failures(self):
        q=OpsQueue.__new__(OpsQueue)
        with patch('pipeline_production.git_queue.GitQueue.git',side_effect=[self.response()]*4+[self.response(0)]) as run, patch('ops_runtime_r4.queue.time.sleep'):
            self.assertEqual(q.git('fetch','origin').returncode,0)
            self.assertEqual(run.call_count,5)

    def test_read_failure_budget_is_finite(self):
        q=OpsQueue.__new__(OpsQueue)
        with patch('pipeline_production.git_queue.GitQueue.git',return_value=self.response()) as run, patch('ops_runtime_r4.queue.time.sleep'):
            with self.assertRaisesRegex(QueueError,'attempts=10'):q.git('ls-remote','origin')
            self.assertEqual(run.call_count,10)

    def test_busy_gate_waits_for_release_without_stealing(self):
        q=OpsQueue.__new__(OpsQueue)
        with patch('pipeline_production.dispatch.DispatchQueue.acquire_claim_gate',side_effect=[ClaimBusy('busy'),ClaimBusy('busy'),{'token':'new'}]) as run, patch('ops_runtime_r4.queue.time.sleep') as sleep:
            self.assertEqual(q.acquire_claim_gate('worker-1'),{'token':'new'})
            self.assertEqual(run.call_count,3)
            self.assertEqual(sleep.call_count,2)

    def test_gate_wait_has_deadline(self):
        q=OpsQueue.__new__(OpsQueue)
        with patch('pipeline_production.dispatch.DispatchQueue.acquire_claim_gate',side_effect=ClaimBusy('busy')) as run, patch('ops_runtime_r4.queue.time.monotonic',side_effect=[0,451]), patch('ops_runtime_r4.queue.time.sleep') as sleep:
            with self.assertRaises(ClaimBusy):q.acquire_claim_gate('worker-1')
            self.assertEqual(run.call_count,1);sleep.assert_not_called()

    def test_claim_finally_cleanup_cannot_mask_a_successful_reservation(self):
        q=OpsQueue.__new__(OpsQueue);q.claim_gate=('gate','token')
        with patch('pipeline_production.git_queue.GitQueue.release_claim_gate',side_effect=QueueError('network')):
            q.release_claim_gate()
        self.assertIsNone(q.claim_gate)

    def test_candidate_expiry_stops_replay(self):
        q,j,old,new=self.setup_queue([],[])
        q,j,old,new=self.setup_queue([self.response()],[old]);q.clock=Mock(side_effect=[100,1001])
        with self.assertRaises(LostLease):self.publish(q,j,old,new)
        self.assertEqual(sum(c.args[0]=='push' for c in q.git.call_args_list),1)

    def test_partial_atomic_observation_is_never_treated_as_success(self):
        q,j,old,new=self.setup_queue([],[],True)
        seen=dict(old);seen[q.ref('dispatch-index')]='index-new'
        q,j,old,new=self.setup_queue([self.response()],[seen],True)
        with self.assertRaisesRegex(QueueError,'inconsistent'):self.publish(q,j,old,new,True)


if __name__=='__main__':unittest.main()
