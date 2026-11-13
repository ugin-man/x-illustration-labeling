"""Local batches survive disconnected Git without relaxing frozen validation."""
import copy
import hashlib
import json
import shutil
import time
import unittest
from unittest.mock import patch

import test_ops_r5_runtime as fixture
from pipeline_production.common import atomic_write, canonical, digest, read_json
from pipeline_production.git_queue import Conflict, LostLease
from ops_batch import worker
from ops_batch.remote import BatchQueue


class BatchRuntimeTests(unittest.TestCase):
    call = fixture.ReconciliationTests.call
    claimed = fixture.ReconciliationTests.claimed
    answer = fixture.ReconciliationTests.answer
    saved = fixture.ReconciliationTests.saved

    def setUp(self):
        fixture.ReconciliationTests.setUp(self)
        self.batch_patch = patch('ops_batch.worker.ROOT', self.root); self.batch_patch.start()
        self.ops_worker = worker
        hashes = {}
        for source in (self.repo / 'ops_batch').glob('*.py'):
            name = source.relative_to(self.repo).as_posix(); target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(source, target)
            hashes[name] = digest(target)
        name = 'docs/WORKER_BATCH.md'; shutil.copyfile(self.repo / name, self.root / name)
        hashes[name] = digest(self.root / name)
        manifest = dict(operations_revision='ops-batch-v1', base_run_id=self.config['run_id'],
            previous_manifest_sha256=digest(self.root / 'ops/revisions/production-v4-001-ops-r5.json'), files_sha256=hashes)
        path = self.root / 'ops/revisions/production-v4-001-ops-batch-v1.json'
        atomic_write(path, canonical(manifest))
        atomic_write(self.root / 'ops/ops-batch-v1-control.json', canonical(dict(
            operations_revision='ops-batch-v1', manifest_sha256=digest(path), state='enabled',
            upgraded_worker_ids=self.config['worker_ids'])))

    def tearDown(self):
        self.batch_patch.stop(); fixture.ReconciliationTests.tearDown(self)

    def queue(self):
        return BatchQueue(self.remote, self.config['run_id'], self.config['catalog_sha256'],
                          self.catalog['jobs'], self.config['worker_ids'])

    def test_all_per_post_operations_have_zero_git_calls(self):
        jid, folder, manifest = self.claimed()
        def fake_fetch(pid, path):
            row = dict(post_id=pid, state='unavailable', text=None)
            atomic_write(path, canonical(row)); return row
        with patch.object(BatchQueue, '__init__', side_effect=AssertionError('Git was instantiated')):
            item = self.call('next', job=jid); pid = item['post_id']
            with patch('ops_batch.worker.context.fetch', side_effect=fake_fetch) as fetch:
                self.call('context', job=jid, post=pid, context_action='fetch')
                self.call('context', job=jid, post=pid, context_action='fetch')
                self.assertEqual(fetch.call_count, 1)
            self.call('context', job=jid, post=pid, context_action='summary')
            row = self.answer(manifest, manifest['posts'][0]); atomic_write(folder / 'draft.json', canonical(row))
            self.assertFalse(self.call('save', job=jid)['remote_accepted'])
            self.assertEqual(self.call('inspect', job=jid)['local_pending_ids'], [pid])
        self.call('checkpoint', job=jid)
        self.assertEqual(self.call('inspect', job=jid)['remote_accepted_count'], 1)

    def test_local_search_reservation_survives_restart_without_duplicate_permission(self):
        jid, folder, manifest = self.claimed(); pid = manifest['posts'][0]['post_id']
        args = dict(job=jid, post=pid, context_action='search', request_id='search-1', query='synthetic')
        self.assertTrue(self.call('context', **args)['permitted'])
        self.assertFalse(self.call('context', **args)['permitted'])
        self.call('checkpoint', job=jid)
        self.call('reconcile', job=jid)
        self.assertFalse(self.call('context', **args)['permitted'])
        self.assertEqual(self.call('context', job=jid, post=pid)['searches'], 1)

    def test_interrupted_fetch_is_local_technical_failure_not_whole_job_defer(self):
        jid, folder, manifest = self.claimed(); pid = manifest['posts'][0]['post_id']
        with patch('ops_batch.worker.context.fetch', side_effect=OSError('synthetic process disconnected')):
            with self.assertRaises(OSError):
                self.call('context', job=jid, post=pid, context_action='fetch')
        with patch('ops_batch.worker.context.fetch', side_effect=AssertionError('Must not fetch again')):
            result = self.call('context', job=jid, post=pid, context_action='fetch')
        self.assertEqual(result['error'], 'prior_fetch_interrupted')
        self.assertEqual(self.call('next', job=jid)['post_id'], pid)
        self.call('checkpoint', job=jid)

    def test_defer_blocks_duplicates_and_keeps_original_then_commits_once(self):
        jid, folder, manifest, post, row = self.saved()
        raw = (folder / 'results' / (post['post_id'] + '.json')).read_bytes()
        self.call('defer', job=jid, post=post['post_id'], reason='approval_required')
        self.assertEqual((folder / 'results' / (post['post_id'] + '.json')).read_bytes(), raw)
        self.assertEqual(self.call('next', job=jid)['post_id'], manifest['posts'][2]['post_id'])
        last = manifest['posts'][2]; atomic_write(folder / 'draft.json', canonical(self.answer(manifest, last)))
        self.call('save', job=jid)
        result = self.call('finish', job=jid)
        self.assertEqual(result['status'], 'needs_review')
        self.assertEqual(result['remote_accepted_count'], 1)
        with self.queue() as q:
            h, state = q.read(jid); names = q.files(h)
            self.assertIn('deferred-' + post['post_id'] + '.json', names)
            self.assertTrue(any(n.startswith('audit-unaccepted-') for n in names))

    def test_policy_refusal_persists_offline_and_never_exposes_duplicate_path(self):
        jid, folder, manifest = self.claimed(); first = manifest['posts'][0]
        with patch.object(BatchQueue, '__init__', side_effect=AssertionError('Git called')):
            self.call('exclude', job=jid, post=first['post_id'], signal='image_tool_refusal', media_index=1)
            result = self.call('next', job=jid)
            self.assertEqual(result['status'], 'known_refusal_requires_exclusion')
            self.assertNotIn('images', result)
            with self.assertRaises(Conflict):
                self.call('context', job=jid, post=first['post_id'], context_action='fetch')
        self.call('checkpoint', job=jid)

    def test_corrupt_file_and_missing_required_fields_still_rejected(self):
        jid, folder, manifest = self.claimed(); post = manifest['posts'][0]
        row = self.answer(manifest, post); del row['characters'][0]['appearances'][0]['attributes']['crop']
        atomic_write(folder / 'draft.json', canonical(row))
        with self.assertRaises(AssertionError): self.call('save', job=jid)
        atomic_write(folder / post['images'][0]['path'], b'changed synthetic bytes')
        with self.assertRaises((AssertionError, ValueError)): self.call('next', job=jid)

    def test_expired_local_lease_stops_new_view_but_saves_existing_work(self):
        jid, folder, manifest = self.claimed(); post = manifest['posts'][0]
        path = worker.state_path(folder); session = read_json(path); session['lease']['lease_until'] = 0
        atomic_write(path, canonical(session))
        with self.assertRaises(LostLease): self.call('next', job=jid)
        atomic_write(folder / 'draft.json', canonical(self.answer(manifest, post)))
        self.call('save', job=jid)
        self.assertEqual(self.call('inspect', job=jid)['local_pending_ids'], [post['post_id']])

    def test_accepted_immutable_and_pending_recovered_without_reclassification(self):
        jid, folder, manifest, post, row = self.saved(True)
        self.assertTrue(self.call('save', job=jid)['remote_accepted'])
        second = manifest['posts'][1]; atomic_write(folder / 'draft.json', canonical(self.answer(manifest, second)))
        self.call('save', job=jid)
        pending = (folder / 'results' / (second['post_id'] + '.json')).read_bytes()
        (folder / 'results' / (post['post_id'] + '.json')).unlink()
        self.call('reconcile', job=jid)
        self.assertEqual((folder / 'results' / (post['post_id'] + '.json')).read_bytes(), canonical(row))
        self.assertEqual((folder / 'results' / (second['post_id'] + '.json')).read_bytes(), pending)
        changed = copy.deepcopy(row); changed['review_flags'] = ['changed']
        atomic_write(folder / 'draft.json', canonical(changed))
        with self.assertRaisesRegex(Conflict, 'immutable'): self.call('save', job=jid)

    def test_lost_finish_response_is_idempotent_and_preserves_all_rows(self):
        jid, folder, manifest = self.claimed()
        for post in manifest['posts']:
            atomic_write(folder / 'draft.json', canonical(self.answer(manifest, post))); self.call('save', job=jid)
        before = worker.state_path(folder).read_bytes()
        first = self.call('finish', job=jid)
        atomic_write(worker.state_path(folder), before)  # Simulate interrupted local receipt after accepted push.
        second = self.call('finish', job=jid)
        self.assertEqual(first['remote_head'], second['remote_head'])
        self.assertEqual(second['status'], 'completed')

    def test_save_interruption_after_result_write_reuses_finished_time(self):
        jid, folder, manifest = self.claimed(); post = manifest['posts'][0]
        row = self.answer(manifest, post); row['execution']['finished_at'] = None
        draft = folder / 'draft.json'; atomic_write(draft, canonical(row))
        real_write = worker.atomic_write
        def interrupted(path, data):
            if path == draft:
                raise OSError('synthetic interruption after result write')
            return real_write(path, data)
        with patch('ops_batch.worker.atomic_write', interrupted):
            with self.assertRaises(OSError): self.call('save', job=jid)
        path = folder / 'results' / (post['post_id'] + '.json'); original = path.read_bytes()
        self.call('save', job=jid)
        self.assertEqual(path.read_bytes(), original)

    def test_unknown_checkpoint_outcome_blocks_revision_but_keeps_new_work_local(self):
        jid, folder, manifest, post, row = self.saved()
        with patch.object(BatchQueue, 'commit_batch', side_effect=OSError('connection gone')):
            with self.assertRaises(OSError): self.call('checkpoint', job=jid)
        changed = copy.deepcopy(row); changed['review_flags'] = ['changed']
        atomic_write(folder / 'draft.json', canonical(changed))
        with self.assertRaisesRegex(Conflict, 'reconcile'):
            self.call('revise', job=jid, post=post['post_id'], reason='test')
        self.assertEqual(self.call('next', job=jid)['post_id'], manifest['posts'][1]['post_id'])
        self.call('checkpoint', job=jid)


class BatchOwnershipTests(unittest.TestCase):
    def test_other_worker_does_not_take_expired_owner_journal(self):
        from test_ops_r3_runtime import OpsQueueTests
        fixture = OpsQueueTests(); fixture.setUp()
        try:
            jobs = fixture.jobs[:1]
            with BatchQueue(fixture.remote, 'synthetic-ops', 'a' * 64, jobs, fixture.workers,
                            clock=lambda: fixture.now) as q:
                first = q.claim(fixture.workers[0])['lease']
                fixture.now += 3721
                self.assertNotIn('lease', q.claim(fixture.workers[1]))
                recovered = q.claim(fixture.workers[0])['lease']
                self.assertEqual(recovered['job_id'], first['job_id'])
                self.assertNotEqual(recovered['token'], first['token'])
                with self.assertRaises(LostLease):
                    q.commit_batch(first['job_id'], first['token'], fixture.workers[0], jobs[0]['manifest'], {}, {})
        finally:
            fixture.tearDown()


if __name__ == '__main__':
    unittest.main()
