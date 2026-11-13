"""Real concurrent Git CAS transactions for the batch ownership boundary."""
from concurrent.futures import ThreadPoolExecutor
import unittest
import test_production_runtime as fixture
from ops_batch.remote import BatchQueue


class BatchDispatchTests(unittest.TestCase):
    setUp = fixture.DispatchTests.setUp
    tearDown = fixture.DispatchTests.tearDown
    test_ten_concurrent_claims_distinct_and_index_job_heads_match = fixture.DispatchTests.test_ten_concurrent_claims_distinct_and_index_job_heads_match
    test_interrupted_ack_is_recovered_without_duplicate_job = fixture.DispatchTests.test_interrupted_ack_is_recovered_without_duplicate_job

    def queue(self, jobs=None):
        return BatchQueue(self.remote, 'production-test', 'a' * 64, jobs or self.jobs,
                          self.workers, clock=lambda: self.now)

    def test_parallel_batch_commits_preserve_each_job_and_index(self):
        leases = []
        for worker in self.workers[:3]:
            with self.queue() as q:
                leases.append(q.claim(worker)['lease'])
        def commit(lease):
            with self.queue() as q:
                spec = next(j for j in self.jobs if j['job_id'] == lease['job_id'])
                pid = spec['post_ids'][0]
                return q.commit_batch(lease['job_id'], lease['token'], lease['worker_id'],
                    dict(job_id=lease['job_id'], posts=[]), {pid: dict(post_id=pid, synthetic=True)}, {})
        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(commit, leases))
        with self.queue() as q:
            _, index = q.read_index()
            for lease, (head, state, metadata) in zip(leases, results):
                entry = index['entries'][lease['job_id']]
                self.assertEqual(entry['head'], head)
                self.assertEqual(entry['completed_posts'], 1)


if __name__ == '__main__':
    unittest.main()
