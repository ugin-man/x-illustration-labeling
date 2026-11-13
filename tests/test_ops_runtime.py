"""Operations revision regressions: synthetic metadata and temporary bare Git only.

These tests never open research media or contact an external service. The frozen
classification implementation is used unchanged for validation.
"""
import base64
import copy
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from pipeline_production.common import atomic_write, canonical, digest, read_json
from pipeline_production.git_queue import Conflict, LostLease, QueueError


def metadata_job(number):
    """Two duplicate inputs and one independent input, without real image bytes."""
    jid = 'job-%02d' % number
    posts = []
    for offset in (1, 2, 3):
        key = '%d-%d' % (number, 2 if offset == 3 else 1)
        sha = hashlib.sha256(key.encode()).hexdigest()
        posts.append(dict(post_id=str(number * 100 + offset), images=[dict(
            media_index=1, sha256=sha, path='images/' + sha + '.jpg')]))
    manifest = dict(dataset_version='synthetic-ops', job_id=jid,
                    split='production', posts=posts)
    return dict(job_id=jid, post_ids=[p['post_id'] for p in posts],
                manifest=manifest, manifest_sha256=hashlib.sha256(canonical(manifest)).hexdigest())


class OpsQueueTests(unittest.TestCase):
    def setUp(self):
        from ops_runtime.queue import OpsQueue
        self.queue_class = OpsQueue
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.remote = self.root / 'remote.git'
        subprocess.run(['git', 'init', '--bare', '--quiet', str(self.remote)], check=True)
        self.now = 10000
        self.jobs = [metadata_job(i) for i in (1, 2, 3)]
        self.workers = ['terra-prod-%02d' % i for i in range(1, 11)]

    def tearDown(self):
        self.tmp.cleanup()

    def queue(self):
        return self.queue_class(self.remote, 'synthetic-ops', 'a' * 64,
                                self.jobs, self.workers, clock=lambda: self.now)

    def budget(self, searches=1, pages=1):
        return canonical(dict(started_at=10000, deadline=10060,
            searches=searches, pages=pages,
            queries=[dict(query='synthetic query %d' % i, reserved_at=10000 + i)
                     for i in range(searches)]))

    def test_deferred_hash_component_blocks_transitive_duplicates_only(self):
        from ops_runtime.queue import blocked_posts, deferred_record
        x, y, z = ('a' * 64, 'b' * 64, 'c' * 64)
        a = dict(post_id='101', images=[dict(media_index=1, sha256=x)])
        b = dict(post_id='102', images=[dict(media_index=1, sha256=x),
                                        dict(media_index=2, sha256=y)])
        c = dict(post_id='103', images=[dict(media_index=1, sha256=y)])
        d = dict(post_id='104', images=[dict(media_index=1, sha256=z)])
        # Reverse dependency order requires another pass: C is visited before B.
        manifest = dict(job_id='job-01', posts=[c, d, b, a])
        deferred = canonical(deferred_record('synthetic-ops', 'job-01', a, 'approval_required'))
        self.assertEqual(blocked_posts(manifest, {'deferred-101.json': deferred}),
                         {'101', '102', '103'})

    def test_sidecars_survive_expiry_and_reassignment_without_accepted_results(self):
        cache = canonical(dict(post_id='101', state='technical_failure',
                               error='synthetic_interrupted_fetch', text=None))
        budget = self.budget()
        with self.queue() as q:
            lease = q.reserve('job-01', self.workers[0])
            q.sync_context('job-01', lease['token'], '101', cache, budget, self.workers[0])
            _, state, before = q.read_metadata('job-01', lease['token'], self.workers[0])
            self.assertEqual(state['completed_posts'], [])
            self.assertIn(cache, before.values())
            self.assertIn(budget, before.values())
        self.now += 3721
        with self.queue() as q:
            successor = q.reserve('job-01', self.workers[1])
            _, state, after = q.read_metadata('job-01', successor['token'], self.workers[1])
            self.assertEqual(after, before)
            self.assertEqual(state['completed_posts'], [])
            with self.assertRaises((Conflict, LostLease, QueueError, ValueError)):
                q.sync_context('job-01', lease['token'], '101', cache, budget, self.workers[0])

    def test_context_cache_cannot_be_replaced_and_budget_deadline_cannot_extend(self):
        cache = canonical(dict(post_id='101', state='unavailable', text=None))
        budget = self.budget()
        with self.queue() as q:
            lease = q.reserve('job-01', self.workers[0])
            args = ('job-01', lease['token'], '101')
            q.sync_context(*args, cache, budget, self.workers[0])
            before = q.read_metadata('job-01', lease['token'], self.workers[0])[2]
            changed_cache = canonical(dict(post_id='101', state='available', text='new retrieval'))
            with self.assertRaises((Conflict, QueueError, ValueError)):
                q.sync_context(*args, changed_cache, budget, self.workers[0])
            changed_budget = json.loads(budget)
            changed_budget.update(started_at=20000, deadline=20060, searches=0, pages=0, queries=[])
            with self.assertRaises((Conflict, QueueError, ValueError)):
                q.sync_context(*args, cache, canonical(changed_budget), self.workers[0])
            self.assertEqual(q.read_metadata('job-01', lease['token'], self.workers[0])[2], before)

    def test_sidecar_writes_require_current_token_and_worker_identity(self):
        with self.queue() as q:
            lease = q.reserve('job-01', self.workers[0])
            before = q.heads()
            with self.assertRaises((Conflict, LostLease, QueueError, ValueError)):
                q.sync_context('job-01', lease['token'], '101',
                    canonical(dict(post_id='101', state='unavailable', text=None)),
                    self.budget(), self.workers[1])
            self.assertEqual(q.heads(), before)

    def test_defer_persists_metadata_without_inventing_completion(self):
        post = self.jobs[0]['manifest']['posts'][0]
        with self.queue() as q:
            lease = q.reserve('job-01', self.workers[0])
            q.defer_post('job-01', lease['token'], post, 'approval_required', self.workers[0])
            head, state, metadata = q.read_metadata('job-01', lease['token'], self.workers[0])
            self.assertEqual(state['completed_posts'], [])
            deferred = json.loads(metadata['deferred-101.json'])
            self.assertEqual(deferred['post_id'], '101')
            self.assertIn(post['images'][0]['sha256'], json.dumps(deferred))
            self.assertNotIn('images/', json.dumps(deferred))
            self.assertEqual(q.read_index()[1]['entries']['job-01']['head'], head)
            with self.assertRaises(QueueError):
                q.finish('job-01', lease['token'], self.jobs[0]['post_ids'])

    def test_sidecar_api_cannot_modify_results_state_or_manifest(self):
        with self.queue() as q:
            lease = q.reserve('job-01', self.workers[0])
            before = q.heads()
            for name in ('post-101.json', 'state.json', 'manifest.json', '../escape.json'):
                with self.subTest(name=name), self.assertRaises((Conflict, QueueError, ValueError)):
                    q.publish_sidecars('job-01', lease['token'], {name: b'{}\n'}, self.workers[0])
            self.assertEqual(q.heads(), before)

    def test_resume_review_preserves_accepted_bytes_and_updates_index_atomically(self):
        manifest = self.jobs[0]['manifest']
        accepted = canonical(dict(post_id='102', synthetic='accepted immutable row'))
        with self.queue() as q:
            lease = q.reserve('job-01', self.workers[0])
            q.checkpoint('job-01', lease['token'], {'102': json.loads(accepted)},
                         manifest=manifest, hold=dict(post_id='101', reason='input_requires_review'))
            head = q.resume_review('job-01', manifest, 'approval_required', 'ops-coordinator')
            remote_head, state = q.read('job-01')
            self.assertEqual(head, remote_head)
            self.assertEqual(state['status'], 'available')
            self.assertEqual(state['completed_posts'], ['102'])
            self.assertEqual(q.git('show', head + ':post-102.json').stdout, accepted)
            self.assertIn('deferred-101.json', q.files(head))
            entry = q.read_index()[1]['entries']['job-01']
            self.assertEqual(entry['head'], head)
            self.assertEqual(entry['status'], 'available')
            self.assertEqual(entry['completed_posts'], 1)

    def test_resume_review_has_no_nonatomic_fallback(self):
        manifest = self.jobs[0]['manifest']
        with self.queue() as q:
            lease = q.reserve('job-01', self.workers[0])
            q.checkpoint('job-01', lease['token'], {}, manifest=manifest,
                         hold=dict(post_id='101', reason='input_requires_review'))
            before = q.heads()
            subprocess.run(['git', '-C', str(self.remote), 'config',
                            'receive.advertiseAtomic', 'false'], check=True)
            with self.assertRaises(QueueError):
                q.resume_review('job-01', manifest, 'approval_required', 'ops-coordinator')
            self.assertEqual(q.heads(), before)
            head, state = q.read('job-01')
            self.assertEqual(state['status'], 'needs_review')
            self.assertNotIn('deferred-101.json', q.files(head))

    def test_revision_audit_rechecks_unaccepted_guard_after_atomic_race(self):
        accepted = {'post_id': '101', 'synthetic': 'accepted during revision preparation'}
        original = canonical(dict(post_id='101', synthetic='prior original evidence'))
        audit = canonical(dict(operations_revision='ops-r2', record_type='unaccepted_history',
            run_id='synthetic-ops', job_id='job-01', post_id='101', worker_id=self.workers[0],
            operation='revise', reason='Synthetic correction', artifacts={'answer.json': dict(
                sha256=hashlib.sha256(original).hexdigest(), bytes=len(original),
                base64=base64.b64encode(original).decode('ascii'))}))
        audit_name = 'audit-unaccepted-101-' + hashlib.sha256(audit).hexdigest() + '.json'
        with self.queue() as a, self.queue() as b:
            lease = a.reserve('job-01', self.workers[0])
            publish = a._publish_atomic
            raced = []

            def accept_before_revision(*args):
                if not raced:
                    raced.append(True)
                    b.checkpoint('job-01', lease['token'], {'101': accepted})
                return publish(*args)

            a._publish_atomic = accept_before_revision
            with self.assertRaises(Conflict):
                a.publish_sidecars('job-01', lease['token'], {audit_name: audit},
                    self.workers[0], must_be_unaccepted=('101',))
            head, state = a.read('job-01')
            self.assertEqual(state['completed_posts'], ['101'])
            self.assertEqual(a.git('show', head + ':post-101.json').stdout, canonical(accepted))
            self.assertNotIn(audit_name, a.files(head))


class OpsRuntimeTests(unittest.TestCase):
    """Run the actual operations entry point against a pinned synthetic fixture."""
    def setUp(self):
        import test_production_runtime as production_tests
        from ops_runtime import worker as ops_worker
        # Reuse only the fixture, not its inherited test methods.
        production_tests.ProductionRuntimeTests.setUp(self)
        self.ops_worker = ops_worker
        self.ops_patch = patch('ops_runtime.worker.ROOT', self.root)
        self.ops_patch.start()
        # Add an independent third input to each pair of equal hashes so defer
        # must skip the duplicate and still expose the remaining safe input.
        for number, job in enumerate(self.catalog['jobs'], 1):
            raw = ('synthetic-independent-input-%d' % number).encode()
            sha = hashlib.sha256(raw).hexdigest()
            post = dict(post_id=str(1000 + number), images=[dict(
                media_index=1, path='images/' + sha + '.jpg', sha256=sha)])
            job['manifest']['posts'].append(post)
            job['post_ids'].append(post['post_id'])
            manifest_bytes = canonical(job['manifest'])
            bundle = self.bundle_dir / job['sources'][0]['asset']
            with zipfile.ZipFile(bundle) as archive:
                existing = [(n, archive.read(n)) for n in archive.namelist() if n != 'manifest.json']
            with zipfile.ZipFile(bundle, 'w') as archive:
                archive.writestr('manifest.json', manifest_bytes)
                for name, data in existing:
                    archive.writestr(name, data)
                archive.writestr(post['images'][0]['path'], raw)
            job['manifest_sha256'] = hashlib.sha256(manifest_bytes).hexdigest()
            job['sources'][0].update(bytes=bundle.stat().st_size, sha256=digest(bundle),
                manifest_sha256=job['manifest_sha256'], post_ids=list(job['post_ids']))
        atomic_write(self.root / 'data/catalog.json', canonical(self.catalog))
        self.config.update(catalog_sha256=digest(self.root / 'data/catalog.json'), max_posts=36)
        atomic_write(self.path, canonical(self.config))
        launch_path = self.root / 'data/launch-control-production.json'
        launch = read_json(launch_path)
        launch.update(run_config_sha256=digest(self.path), catalog_sha256=self.config['catalog_sha256'], max_posts=36)
        atomic_write(launch_path, canonical(launch))
        hashes = {}
        for source in (self.repo / 'ops_runtime').glob('*.py'):
            name = source.relative_to(self.repo).as_posix()
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            hashes[name] = digest(target)
        ops_manual = 'docs/WORKER_OPERATIONS_R2.md'
        shutil.copyfile(self.repo / ops_manual, self.root / ops_manual)
        hashes[ops_manual] = digest(self.root / ops_manual)
        self.ops_manifest = dict(operations_revision='ops-r2', base_run_id=self.config['run_id'],
            base_config_sha256=digest(self.path), base_commit='4d2c98374a1364faf1e2b546a4c460e80e9b2903',
            classification_manual_sha256=self.config['manual_sha256'], files_sha256=hashes)
        self.ops_manifest_path = self.root / 'ops/revisions/production-v4-001-ops-r2.json'
        atomic_write(self.ops_manifest_path, canonical(self.ops_manifest))
        self.control_path = self.root / 'ops/ops-r2-control.json'
        atomic_write(self.control_path, canonical(dict(state='enabled', operations_revision='ops-r2',
            base_run_id=self.config['run_id'], manifest_sha256=digest(self.ops_manifest_path),
            upgraded_worker_ids=self.config['worker_ids'], coordinator_ids=['ops-coordinator'])))

    def tearDown(self):
        self.ops_patch.stop()
        self.patch.stop()
        self.tmp.cleanup()

    def call(self, command, **kw):
        args = SimpleNamespace(config=self.path, remote=None, command=command, job=None,
            worker=self.config['worker_ids'][0], bundle_dir=str(self.bundle_dir), input=None,
            post=None, reason='needs_quality_review', context_action='summary', signal=None,
            media_index=None, query=None, request_id=None)
        for key, value in kw.items():
            setattr(args, key, value)
        output = io.StringIO()
        with redirect_stdout(output):
            self.ops_worker.run(args)
        return json.loads(output.getvalue())

    def claimed(self):
        claim = self.call('claim')
        folder = Path(claim['folder'])
        return claim['job_id'], folder, read_json(folder / 'manifest.json')

    def answer(self, manifest, post, worker_id=None):
        from pipeline_production import worker
        from test_v4_runtime import synthetic
        return synthetic(post, worker.provenance(self.config, manifest),
                         worker_id or self.config['worker_ids'][0])

    def test_revise_preserves_original_and_rejects_remote_accepted_overwrite(self):
        jid, folder, manifest = self.claimed()
        post = manifest['posts'][0]
        old = self.answer(manifest, post)
        atomic_write(folder / 'draft.json', canonical(old))
        self.call('save', job=jid)
        changed = copy.deepcopy(old)
        changed['images'][0]['attributes']['technique']['evidence'] = 'synthetic corrected evidence'
        atomic_write(folder / 'draft.json', canonical(changed))
        self.call('revise', job=jid, post=post['post_id'], reason='Correct synthetic evidence')
        self.assertEqual(read_json(folder / 'results' / (post['post_id'] + '.json')), changed)
        # The old raw answer must remain in durable history, not only in memory.
        from ops_runtime.queue import OpsQueue
        with OpsQueue(self.remote, self.config['run_id'], self.config['catalog_sha256'],
                      self.catalog['jobs'], self.config['worker_ids']) as q:
            head, _ = q.read(jid)
            historical_bytes = []
            for name in q.files(head):
                if not name.startswith('audit-unaccepted-'):
                    continue
                audit = json.loads(q.git('show', head + ':' + name).stdout)
                for artifact in audit['artifacts'].values():
                    raw = base64.b64decode(artifact['base64'], validate=True)
                    self.assertEqual(artifact['bytes'], len(raw))
                    self.assertEqual(artifact['sha256'], hashlib.sha256(raw).hexdigest())
                    historical_bytes.append(raw)
            self.assertIn(canonical(old), historical_bytes)
        stale_lease = (folder / 'lease.json').read_bytes()
        self.call('checkpoint', job=jid)
        # A still-valid but stale local lease must not hide remote acceptance.
        atomic_write(folder / 'lease.json', stale_lease)
        changed_again = copy.deepcopy(changed)
        changed_again['images'][0]['attributes']['technique']['evidence'] = 'second correction'
        atomic_write(folder / 'draft.json', canonical(changed_again))
        with self.assertRaises((Conflict, QueueError, ValueError)):
            self.call('revise', job=jid, post=post['post_id'], reason='Must reject accepted overwrite')
        self.assertEqual(read_json(folder / 'results' / (post['post_id'] + '.json')), changed)

    def test_revise_cannot_replace_another_workers_unaccepted_answer(self):
        jid, folder, manifest = self.claimed()
        post = manifest['posts'][0]
        original = canonical(self.answer(manifest, post, self.config['worker_ids'][1]))
        path = folder / 'results' / (post['post_id'] + '.json')
        atomic_write(path, original)
        atomic_write(folder / 'draft.json', canonical(self.answer(manifest, post)))
        with self.assertRaises((Conflict, QueueError, ValueError)):
            self.call('revise', job=jid, post=post['post_id'], reason='Must preserve other author')
        self.assertEqual(path.read_bytes(), original)

    def test_revise_cannot_replace_policy_exclusion_or_bypass_frozen_validator(self):
        from pipeline_production import disposition, worker
        jid, folder, manifest = self.claimed()
        excluded_post, _, invalid_post = manifest['posts']
        exclusion = disposition.create(excluded_post, worker.provenance(self.config, manifest),
            self.config['worker_ids'][0], 'image_tool_refusal', 1)
        excluded_path = folder / 'results' / (excluded_post['post_id'] + '.json')
        atomic_write(excluded_path, canonical(exclusion))
        atomic_write(folder / 'draft.json', canonical(self.answer(manifest, excluded_post)))
        with self.assertRaises((AssertionError, Conflict, QueueError, ValueError)):
            self.call('revise', job=jid, post=excluded_post['post_id'], reason='Must preserve exclusion')
        self.assertEqual(excluded_path.read_bytes(), canonical(exclusion))
        old = self.answer(manifest, invalid_post)
        invalid_path = folder / 'results' / (invalid_post['post_id'] + '.json')
        atomic_write(invalid_path, canonical(old))
        invalid = copy.deepcopy(old)
        del invalid['characters'][0]['appearances'][0]['attributes']['crop']
        atomic_write(folder / 'draft.json', canonical(invalid))
        with self.assertRaises((AssertionError, Conflict, QueueError, ValueError)):
            self.call('revise', job=jid, post=invalid_post['post_id'], reason='Invalid missing required crop')
        self.assertEqual(invalid_path.read_bytes(), canonical(old))

    def test_defer_skips_post_and_same_hash_but_preserves_other_work_and_unresolved_count(self):
        jid, folder, manifest = self.claimed()
        first, duplicate, independent = manifest['posts']
        atomic_write(folder / 'draft.json', canonical(self.answer(manifest, first)))
        self.call('save', job=jid)
        self.call('defer', job=jid, post=first['post_id'], reason='approval_required')
        result = self.call('next', job=jid)
        self.assertEqual(result['post_id'], independent['post_id'])
        self.assertNotIn(first['images'][0]['sha256'], json.dumps(result))
        atomic_write(folder / 'draft.json', canonical(self.answer(manifest, independent)))
        self.call('save', job=jid)
        self.call('checkpoint', job=jid)
        status = self.call('status')
        entry = next(item for item in status['jobs'] if item['job_id'] == jid)
        self.assertEqual(entry['completed_posts'], 1)
        self.assertNotEqual(entry['status'], 'completed')
        self.assertNotIn('images', self.call('next', job=jid))
        finished = self.call('finish', job=jid)
        self.assertEqual(finished['status'], 'needs_review')
        held = next(item for item in self.call('status')['jobs'] if item['job_id'] == jid)
        self.assertEqual(held['status'], 'needs_review')
        self.assertEqual(held['completed_posts'], 1)
        self.assertNotEqual(self.call('claim')['job_id'], jid)

    def test_deferred_inputs_cannot_be_reopened_by_context_save_or_revise(self):
        jid, folder, manifest = self.claimed()
        first, duplicate, _ = manifest['posts']
        self.call('defer', job=jid, post=first['post_id'], reason='approval_required')
        for post in (first, duplicate):
            atomic_write(folder / 'draft.json', canonical(self.answer(manifest, post)))
            for command in ('context', 'save', 'revise'):
                with self.subTest(post=post['post_id'], command=command), self.assertRaises(
                        (AssertionError, Conflict, QueueError, ValueError)):
                    self.call(command, job=jid, post=post['post_id'],
                              context_action='fetch', reason='Must not revisit deferred input')

    def test_disabled_or_unacknowledged_revision_fails_before_claim(self):
        control = read_json(self.control_path)
        for changed in (dict(control, state='staging'),
                        dict(control, upgraded_worker_ids=self.config['worker_ids'][:-1])):
            atomic_write(self.control_path, canonical(changed))
            with self.subTest(control=changed), self.assertRaises((AssertionError, QueueError, ValueError)):
                self.call('claim')
        refs = subprocess.run(['git', '-C', str(self.remote), 'show-ref'], capture_output=True, check=False)
        self.assertFalse(refs.stdout)

    def test_next_still_checks_actual_file_hash_before_exposing_a_path(self):
        jid, folder, manifest = self.claimed()
        post = manifest['posts'][0]
        (folder / post['images'][0]['path']).write_bytes(b'synthetic changed bytes')
        with self.assertRaises((AssertionError, QueueError, ValueError)):
            self.call('next', job=jid)

    def test_expired_context_ledger_is_preserved_without_another_search(self):
        jid, folder, manifest = self.claimed()
        post = manifest['posts'][0]
        started = time.time() - 120
        budget = dict(started_at=started, deadline=started + 60, searches=1, pages=0,
                      queries=[dict(query='synthetic earlier query', reserved_at=started + 1)])
        path = folder / 'context' / (post['post_id'] + '-budget.json')
        atomic_write(path, canonical(budget))
        result = self.call('context', job=jid, post=post['post_id'], context_action='search',
                           query='synthetic later query', request_id='search-2')
        self.assertFalse(result['permitted'])
        self.assertEqual(read_json(path), budget)

    def test_interrupted_fetch_has_durable_marker_and_never_refetches(self):
        from ops_runtime.queue import OpsQueue
        jid, folder, manifest = self.claimed()
        post = manifest['posts'][0]
        pid = post['post_id']

        def interrupt_after_durable_reservation(*args, **kwargs):
            lease = read_json(folder / 'lease.json')
            with OpsQueue(self.remote, self.config['run_id'], self.config['catalog_sha256'],
                          self.catalog['jobs'], self.config['worker_ids']) as q:
                metadata = q.read_metadata(jid, lease['token'], self.config['worker_ids'][0])[2]
                self.assertIn('context-fetch-' + pid + '.json', metadata)
            raise KeyboardInterrupt('Synthetic termination before fetch result is cached')

        with patch('pipeline_production.context.fetch', side_effect=interrupt_after_durable_reservation) as fetch:
            with self.assertRaises(KeyboardInterrupt):
                self.call('context', job=jid, post=pid, context_action='fetch')
            self.assertEqual(fetch.call_count, 1)
        with patch('pipeline_production.context.fetch', side_effect=AssertionError('Must not refetch')) as fetch:
            result = self.call('context', job=jid, post=pid, context_action='fetch')
            fetch.assert_not_called()
        self.assertEqual(result['state'], 'technical_failure')
        self.assertIn('attempted_at', result)
        self.assertIn('recovered_at', result)
        self.assertNotIn('retrieved_at', result)
        self.assertEqual(read_json(folder / 'context' / (pid + '.json')), result)

    def put_legacy_context(self, folder, post):
        pid = post['post_id']
        started = time.time() - 120
        cache = canonical(dict(post_id=pid, state='unavailable', text=None))
        budget = canonical(dict(started_at=started, deadline=started + 60, searches=1, pages=0,
            queries=[dict(query='synthetic legacy query', reserved_at=started + 1)]))
        atomic_write(folder / 'context' / (pid + '.json'), cache)
        atomic_write(folder / 'context' / (pid + '-budget.json'), budget)
        return {'context-cache-' + pid + '.json': cache, 'context-budget-' + pid + '.json': budget}

    def test_release_preserves_legacy_context_before_handoff(self):
        from ops_runtime.queue import OpsQueue
        jid, folder, manifest = self.claimed()
        expected = self.put_legacy_context(folder, manifest['posts'][0])
        self.call('release', job=jid)
        with OpsQueue(self.remote, self.config['run_id'], self.config['catalog_sha256'],
                      self.catalog['jobs'], self.config['worker_ids'], clock=lambda: time.time() + 601) as q:
            successor = q.reserve(jid, self.config['worker_ids'][1])
            metadata = q.read_metadata(jid, successor['token'], self.config['worker_ids'][1])[2]
            for name, raw in expected.items():
                self.assertEqual(metadata.get(name), raw)

    def test_defer_without_answer_preserves_context_for_post_and_duplicate(self):
        from ops_runtime.queue import OpsQueue
        jid, folder, manifest = self.claimed()
        first, duplicate, _ = manifest['posts']
        expected = self.put_legacy_context(folder, first)
        expected.update(self.put_legacy_context(folder, duplicate))
        self.call('defer', job=jid, post=first['post_id'], reason='approval_required')
        lease = read_json(folder / 'lease.json')
        with OpsQueue(self.remote, self.config['run_id'], self.config['catalog_sha256'],
                      self.catalog['jobs'], self.config['worker_ids']) as q:
            metadata = q.read_metadata(jid, lease['token'], self.config['worker_ids'][0])[2]
            for name, raw in expected.items():
                self.assertEqual(metadata.get(name), raw)

    def test_refusal_exclusion_does_not_validate_or_checkpoint_another_broken_answer(self):
        from ops_runtime.queue import OpsQueue
        jid, folder, manifest = self.claimed()
        refused, duplicate, independent = manifest['posts']
        valid = self.answer(manifest, independent)
        broken = copy.deepcopy(valid)
        del broken['characters'][0]['appearances'][0]['attributes']['crop']
        broken_path = folder / 'results' / (independent['post_id'] + '.json')
        atomic_write(broken_path, canonical(broken))
        # The signal is synthetic: no research image/model call occurs in tests.
        self.call('exclude', job=jid, post=refused['post_id'], signal='model_refusal', media_index=1)
        self.assertEqual(broken_path.read_bytes(), canonical(broken))
        with OpsQueue(self.remote, self.config['run_id'], self.config['catalog_sha256'],
                      self.catalog['jobs'], self.config['worker_ids']) as q:
            head, state = q.read(jid)
            self.assertEqual(state['completed_posts'], [refused['post_id']])
            self.assertNotIn('post-' + independent['post_id'] + '.json', q.files(head))
        atomic_write(folder / 'draft.json', canonical(valid))
        self.call('revise', job=jid, post=independent['post_id'], reason='Repair unrelated synthetic missing crop')
        result = self.call('next', job=jid)
        self.assertEqual(result['status'], 'known_refusal_requires_exclusion')
        self.assertEqual(result['post_id'], duplicate['post_id'])
        self.assertNotIn('images', result)

    def test_context_conflict_can_be_deferred_without_replacing_remote_or_losing_local_bytes(self):
        from ops_runtime.queue import OpsQueue
        jid, folder, manifest = self.claimed()
        first, _, independent = manifest['posts']
        pid = first['post_id']
        cache = folder / 'context' / (pid + '.json')
        original = canonical(dict(post_id=pid, state='unavailable', text=None))
        atomic_write(cache, original)
        self.call('context', job=jid, post=pid, context_action='summary')
        conflicting = canonical(dict(post_id=pid, state='technical_failure', text=None,
                                     error='synthetic preserved divergent local history'))
        atomic_write(cache, conflicting)
        self.call('defer', job=jid, post=pid, reason='context_record_mismatch')
        lease = read_json(folder / 'lease.json')
        with OpsQueue(self.remote, self.config['run_id'], self.config['catalog_sha256'],
                      self.catalog['jobs'], self.config['worker_ids']) as q:
            _, state, metadata = q.read_metadata(jid, lease['token'], self.config['worker_ids'][0])
            self.assertEqual(state['completed_posts'], [])
            self.assertEqual(metadata['context-cache-' + pid + '.json'], original)
            self.assertIn('deferred-' + pid + '.json', metadata)
            preserved = []
            for name, raw in metadata.items():
                if name.startswith('audit-unaccepted-'):
                    for artifact in json.loads(raw)['artifacts'].values():
                        recovered = base64.b64decode(artifact['base64'], validate=True)
                        self.assertEqual(hashlib.sha256(recovered).hexdigest(), artifact['sha256'])
                        preserved.append(recovered)
            self.assertIn(conflicting, preserved)
        self.assertEqual(self.call('next', job=jid)['post_id'], independent['post_id'])

    def test_context_request_replay_does_not_spend_again_or_authorize_another_search(self):
        jid, folder, manifest = self.claimed()
        pid = manifest['posts'][0]['post_id']
        ledger = folder / 'context' / (pid + '-budget.json')
        with self.assertRaises(ValueError):
            self.call('context', job=jid, post=pid, context_action='search',
                      request_id='search-2', query='synthetic out of order')
        self.assertFalse(ledger.exists())
        first = self.call('context', job=jid, post=pid, context_action='search',
                          request_id='search-1', query='synthetic query one')
        self.assertTrue(first['permitted'])
        recorded = ledger.read_bytes()
        second = self.call('context', job=jid, post=pid, context_action='search',
                           request_id='search-1', query='synthetic query one')
        self.assertFalse(second['permitted'])
        self.assertTrue(second['replayed'])
        self.assertEqual(ledger.read_bytes(), recorded)
        self.assertEqual(read_json(ledger)['searches'], 1)


if __name__ == '__main__':
    unittest.main()
