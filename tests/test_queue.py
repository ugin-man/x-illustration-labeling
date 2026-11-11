import concurrent.futures
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest

from pipeline.git_queue import Conflict, GitQueue, LostLease, QueueError


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.remote = Path(self.tmp.name) / 'remote.git'
        subprocess.run(['git', 'init', '--bare', '--quiet', str(self.remote)], check=True)
        self.now = 10000
        self.q = GitQueue(self.remote, 'test-run', 'a' * 64, clock=lambda: self.now)

    def tearDown(self):
        self.q.close()
        self.tmp.cleanup()

    def test_parallel_reservations_have_one_winner(self):
        barrier = threading.Barrier(8)
        def claim(n):
            with GitQueue(self.remote, 'test-run', 'a' * 64, clock=lambda: self.now) as q:
                original = q._publish
                def synchronized(*args):
                    barrier.wait(timeout=30)
                    return original(*args)
                q._publish = synchronized
                try:
                    return bool(q.reserve('job-1', f'worker-{n}'))
                except Conflict:
                    return False
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            winners = list(pool.map(claim, range(8)))
        self.assertEqual(sum(winners), 1)

    def test_expiry_preserves_saved_posts_and_fences_old_owner(self):
        first = self.q.reserve('job-1', 'worker-1')
        self.q.checkpoint('job-1', first['token'], {'123': {'post_id': '123'}})
        self.now += 3601
        self.assertIsNone(self.q.reserve('job-1', 'worker-2'))  # grace period
        self.now += 120
        second = self.q.reserve('job-1', 'worker-2')
        self.assertEqual(second['attempt'], 2)
        with self.assertRaises(LostLease):
            self.q.checkpoint('job-1', first['token'], {'124': {}})
        self.assertEqual(self.q.restore('job-1', Path(self.tmp.name) / 'restored'), 1)
        with self.assertRaises(QueueError):
            self.q.finish('job-1', second['token'], ['123', '124'])
        self.q.checkpoint('job-1', second['token'], {'124': {'post_id': '124'}})
        self.q.finish('job-1', second['token'], ['123', '124'])
        sha, state = self.q.read('job-1')
        self.assertEqual(state['status'], 'completed')
        self.assertEqual(len(self.q.git('show', sha + ':labels.jsonl').stdout.splitlines()), 2)
        self.assertIsNone(self.q.reserve('job-1', 'worker-3'))

    def test_conflicting_results_never_overwrite(self):
        lease = self.q.reserve('job-1', 'worker-1')
        self.q.checkpoint('job-1', lease['token'], {'123': {'value': 'first'}})
        with self.assertRaises(Conflict):
            self.q.checkpoint('job-1', lease['token'], {'123': {'value': 'other'}})

    def test_release_backoff_and_catalog_mismatch(self):
        lease = self.q.reserve('job-1', 'worker-1')
        self.q.release('job-1', lease['token'], 'network_down')
        self.assertIsNone(self.q.reserve('job-1', 'worker-2'))
        self.now += 601
        self.assertIsNotNone(self.q.reserve('job-1', 'worker-2'))
        with GitQueue(self.remote, 'test-run', 'b' * 64) as other:
            with self.assertRaises(QueueError):
                other.read('job-1')

    def test_stale_sibling_cannot_replace_accepted_checkpoint(self):
        lease = self.q.reserve('job-1', 'worker-1')
        old_head, old_state = self.q.read('job-1')
        old_state['updated_at'] += 1
        stale = self.q._commit(old_state, old_head)
        self.q.checkpoint('job-1', lease['token'], {'123': {}})
        with self.assertRaises(Conflict):
            self.q._publish('job-1', old_head, stale)


if __name__ == '__main__':
    unittest.main()
