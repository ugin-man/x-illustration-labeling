import copy
import unittest

from ops.watch_snapshot import snapshot


class WatchSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.config = {'run_id': 'watch-test', 'catalog_sha256': 'a' * 64,
                       'queue_version': 'dispatch-v1', 'worker_ids': ['terra-prod-01'], 'job_ids': ['prod-0001']}
        self.catalog = {'jobs': [{'job_id': 'prod-0001', 'post_ids': ['100', '101']}]}
        self.state = {**{k: self.config[k] for k in ('run_id', 'catalog_sha256', 'queue_version', 'worker_ids')},
                      'updated_at': 900, 'entries': {'prod-0001': {'status': 'assigned',
                      'post_count': 2, 'completed_posts': 2, 'worker_id': 'terra-prod-01',
                      'lease_until': 1500, 'head': 'b' * 40, 'retry_after': 0,
                      'dispatch_token': 'never-output-this-token'}}}

    def test_all_rows_checkpointed_is_not_job_completion(self):
        out = snapshot(self.config, self.catalog, self.state, now=1000)
        self.assertEqual(out['unresolved_posts'], 0)
        self.assertFalse(out['all_jobs_completed'])
        self.assertEqual(out['counts'], {'leased': 1})
        self.assertEqual(out['workers'][0]['worker_id'], 'terra-prod-01')
        self.assertNotIn('never-output-this-token', str(out))
        final = copy.deepcopy(self.state)
        final['entries']['prod-0001'].update(status='completed', worker_id=None, lease_until=0)
        self.assertTrue(snapshot(self.config, self.catalog, final, now=1000)['all_jobs_completed'])

    def test_expired_lease_grace_and_reclaimable_are_distinct(self):
        self.assertEqual(snapshot(self.config, self.catalog, self.state, now=1550)['counts'], {'expired_grace': 1})
        self.assertEqual(snapshot(self.config, self.catalog, self.state, now=1620)['claimable_jobs'], 1)

    def test_wrong_scope_is_rejected(self):
        self.state['catalog_sha256'] = 'c' * 64
        with self.assertRaises(AssertionError):
            snapshot(self.config, self.catalog, self.state, now=1000)


if __name__ == '__main__':
    unittest.main()
