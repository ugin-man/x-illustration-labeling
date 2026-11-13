"""Exercise r4's new publisher against real local atomic Git transactions."""
import unittest
import test_production_runtime as fixture
from ops_runtime_r4.queue import OpsQueue


class DispatchRecoveryTests(unittest.TestCase):
    setUp = fixture.DispatchTests.setUp
    tearDown = fixture.DispatchTests.tearDown
    test_ten_concurrent_claims_distinct_and_index_job_heads_match = fixture.DispatchTests.test_ten_concurrent_claims_distinct_and_index_job_heads_match
    test_interrupted_ack_is_recovered_without_duplicate_job = fixture.DispatchTests.test_interrupted_ack_is_recovered_without_duplicate_job
    test_parallel_checkpoints_retry_only_atomic_conflicts_and_preserve_immutable_results = fixture.DispatchTests.test_parallel_checkpoints_retry_only_atomic_conflicts_and_preserve_immutable_results

    def queue(self, jobs=None):
        return OpsQueue(self.remote, 'production-test', 'a' * 64,
                        jobs or self.jobs, self.workers, clock=lambda: self.now)


if __name__ == '__main__':
    unittest.main()
