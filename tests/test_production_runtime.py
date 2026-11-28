"""Production queue regression tests: synthetic bytes and temporary bare Git only."""
import concurrent.futures
import copy
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from pipeline_production import worker, contract_v4, disposition
from pipeline_production.bundles import prepare_job
from pipeline_production.common import atomic_write, canonical, digest, read_json
from pipeline_production.dispatch import DispatchQueue, INDEX_JOB, AtomicConflict
from pipeline_production.git_queue import GitQueue, Conflict, ClaimBusy, LostLease, QueueError
from pipeline_production.launch_control import require_launch
from pipeline_production.toolchain import FILES, fingerprint
from pipeline_production.collect import collect
from test_v4_runtime import synthetic


class DispatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.remote = self.root / 'remote.git'
        subprocess.run(['git', 'init', '--bare', '--quiet', str(self.remote)], check=True)
        self.now = 10000
        self.jobs = [{'job_id': 'job-%02d' % i, 'post_ids': [str(i)]} for i in range(1, 13)]
        self.workers = ['terra-prod-%02d' % i for i in range(1, 11)]

    def tearDown(self):
        self.tmp.cleanup()

    def queue(self, jobs=None):
        return DispatchQueue(self.remote, 'production-test', 'a' * 64,
                             jobs or self.jobs, self.workers, clock=lambda: self.now)

    def test_ten_concurrent_claims_distinct_and_index_job_heads_match(self):
        def claim(w):
            with self.queue() as q:
                return q.claim(w)['lease']
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            leases = list(pool.map(claim, self.workers))
        self.assertEqual(len({s['job_id'] for s in leases}), 10)
        with self.queue() as q:
            _, index = q.read_index()
            assigned = {j: e for j, e in index['entries'].items() if e['status'] == 'assigned'}
            self.assertEqual(len(assigned), 10)
            for lease in leases:
                head, state = q.read(lease['job_id'])
                self.assertEqual(assigned[lease['job_id']]['head'], head)
                self.assertEqual(assigned[lease['job_id']]['dispatch_token'], state['token'])

    def test_same_identity_concurrent_claims_cannot_take_two_jobs(self):
        def claim(_):
            with self.queue() as q:
                try:
                    return q.claim(self.workers[0])
                except ClaimBusy:
                    return {'status': 'busy'}
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(claim, range(4)))
        with self.queue() as q:
            _, index = q.read_index()
            self.assertEqual(sum(e['status'] == 'assigned' for e in index['entries'].values()), 1)

    def test_delayed_initial_claim_cannot_create_orphan_or_second_assignment(self):
        # Freeze A after both candidates are constructed but BEFORE atomic publish.
        # B reserves A's target; stale A must publish neither its index nor its job.
        with self.queue() as a, self.queue() as b:
            original = a._publish_atomic
            pending = []
            def suspend(*args):
                pending.append(args)
                raise RuntimeError('synthetic process interruption before atomic push')
            a._publish_atomic = suspend
            with self.assertRaises(RuntimeError):
                a.reserve('job-01', self.workers[0])
            self.now += 1000  # A can be delayed arbitrarily; no intent lease exists.
            successor = b.reserve('job-01', self.workers[1])
            other = b.reserve('job-02', self.workers[0])
            with self.assertRaises(AtomicConflict):
                original(*pending[0])
            _, index = b.read_index()
            self.assertEqual(index['entries']['job-01']['head'], successor['head'])
            self.assertEqual(index['entries']['job-02']['head'], other['head'])
            self.assertEqual(b.read('job-01')[1]['worker_id'], self.workers[1])

    def test_index_conflict_rejects_otherwise_valid_new_job_atomically(self):
        with self.queue() as a, self.queue() as b:
            original = a._publish_atomic
            pending = []
            def suspend(*args):
                pending.append(args)
                raise RuntimeError('interrupted')
            a._publish_atomic = suspend
            with self.assertRaises(RuntimeError):
                a.reserve('job-01', self.workers[0])
            b.reserve('job-02', self.workers[1])
            with self.assertRaises(AtomicConflict):
                original(*pending[0])
            self.assertIsNone(b.read('job-01')[0])  # atomic rollback, no orphan branch
            self.assertEqual(b.read_index()[1]['entries']['job-01']['status'], 'pending')

    def test_server_without_atomic_push_fails_closed_without_any_job_or_index(self):
        subprocess.run(['git', '-C', str(self.remote), 'config', 'receive.advertiseAtomic', 'false'], check=True)
        with self.queue() as q:
            with self.assertRaisesRegex(QueueError, 'Atomic Git transaction'):
                q.reserve('job-01', self.workers[0])
            self.assertEqual(q.heads(), {})

    def test_expiry_preserves_checkpoint_and_fences_old_and_delayed_writers(self):
        jobs = [dict(job_id='job-01', post_ids=['1', '2'])]
        with self.queue(jobs) as a, self.queue(jobs) as b:
            first = a.claim(self.workers[0])['lease']
            a.checkpoint('job-01', first['token'], {'1': {'post_id': '1'}})
            # Prepare an old checkpoint candidate before expiry, but delay its push.
            pending = []
            original = a._publish_atomic
            def suspend(*args):
                pending.append(args)
                raise RuntimeError('interrupted')
            a._publish_atomic = suspend
            with self.assertRaises(RuntimeError):
                a.checkpoint('job-01', first['token'], {'2': {'post_id': '2'}})
            self.now += 3601
            self.assertEqual(b.claim(self.workers[0])['status'], 'retry_after')
            self.now += 120
            second = b.claim(self.workers[1])['lease']
            self.assertEqual(second['completed_posts'], ['1'])
            with self.assertRaises(AtomicConflict):
                original(*pending[0])
            a._publish_atomic = original
            with self.assertRaises(LostLease):
                a.checkpoint('job-01', first['token'], {'2': {'post_id': '2'}})
            restored = self.root / 'restored'
            self.assertEqual(b.restore('job-01', restored), 1)
            self.assertEqual(read_json(restored / '1.json'), {'post_id': '1'})
            b.checkpoint('job-01', second['token'], {'2': {'post_id': '2'}})
            b.finish('job-01', second['token'], ['1', '2'])
            self.assertEqual(b.status()['status'], 'all_done')

    def test_interrupted_ack_is_recovered_without_duplicate_job(self):
        with self.queue() as q:
            original = q.git
            lost = []
            def lose_ack(*args, **kwargs):
                result = original(*args, **kwargs)
                if args[:2] == ('push', '--atomic') and not lost:
                    self.assertEqual(result.returncode, 0)
                    lost.append(True)
                    return subprocess.CompletedProcess(args, 1, result.stdout, b'synthetic lost acknowledgement')
                return result
            q.git = lose_ack
            first = q.claim(self.workers[0])['lease']
            resumed = q.claim(self.workers[0])
            self.assertEqual(resumed['status'], 'active_job_exists')
            self.assertEqual(resumed['lease']['job_id'], first['job_id'])
            self.assertEqual(resumed['lease']['token'], first['token'])

    def test_parallel_checkpoints_retry_only_atomic_conflicts_and_preserve_immutable_results(self):
        leases = []
        with self.queue() as q:
            for w in self.workers[:3]:
                leases.append(q.claim(w)['lease'])
        barrier = threading.Barrier(3)
        def checkpoint(lease):
            with self.queue() as q:
                original = q._publish_atomic
                calls = []
                def synchronize(*args):
                    if not calls:
                        calls.append(True)
                        barrier.wait(timeout=30)
                    return original(*args)
                q._publish_atomic = synchronize
                pid = next(j['post_ids'][0] for j in self.jobs if j['job_id'] == lease['job_id'])
                return q.checkpoint(lease['job_id'], lease['token'], {pid: {'post_id': pid}})
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            self.assertEqual(len(list(pool.map(checkpoint, leases))), 3)
        with self.queue() as q:
            self.assertEqual(q.status()['checkpointed_posts'], 3)
            lease = leases[0]
            pid = next(j['post_ids'][0] for j in self.jobs if j['job_id'] == lease['job_id'])
            with self.assertRaises(Conflict):
                q.checkpoint(lease['job_id'], lease['token'], {pid: {'post_id': pid, 'changed': True}})

    def test_status_is_read_only_token_free_and_distinguishes_tail_states(self):
        jobs = [self.jobs[0]]
        with self.queue(jobs) as q:
            before = q.heads()
            self.assertEqual(q.status()['status'], 'available')
            self.assertEqual(q.heads(), before)
            lease = q.claim(self.workers[0])['lease']
            self.assertEqual(q.claim(self.workers[1])['status'], 'all_leased')
            before = q.heads()
            status = q.status()
            self.assertNotIn(lease['token'], json.dumps(status))
            self.assertNotIn('dispatch_token', json.dumps(status))
            self.assertEqual(q.heads(), before)
            q.release('job-01', lease['token'], 'synthetic retry', retry_seconds=60)
            self.assertEqual(q.status()['status'], 'retry_after')
            self.now += 61
            self.assertEqual(q.status()['status'], 'available')
            second = q.claim(self.workers[1])['lease']
            q.checkpoint('job-01', second['token'], {},
                         hold={'post_id': '1', 'reason': 'schema_ambiguity'})
            self.assertEqual(q.status()['status'], 'needs_review')

    def test_hundreds_of_jobs_do_not_add_remote_reads_to_normal_claim_or_status(self):
        self.jobs = [{'job_id': 'job-%04d' % i, 'post_ids': [str(i)]} for i in range(1, 414)]
        with self.queue() as q:
            remote_reads = []
            original = q.git
            def track(*args, **kwargs):
                if args[0] in {'fetch', 'ls-remote'}:
                    remote_reads.append(args)
                return original(*args, **kwargs)
            q.git = track
            q.claim(self.workers[0])
            self.assertLess(len(remote_reads), 15)
            remote_reads.clear()
            self.assertEqual(q.status()['counts']['pending'], 412)
            self.assertEqual(len(remote_reads), 2)  # index ls-remote + one fetch


class ProductionRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = Path(__file__).resolve().parents[1]
        for name in set(FILES) | {'docs/LABELING_V4_PRODUCTION.md'}:
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(self.repo / name, target)
        self.policy = {'version': 1, 'screening_receipt_sha256': 'a'*64,
                       'post_ids': ['999'], 'image_sha256': ['f'*64]}
        atomic_write(self.root / 'data/exclusion.json', canonical(self.policy))
        self.bundle_dir = self.root / 'bundles'
        self.bundle_dir.mkdir()
        jobs = []
        for i in range(1, 13):
            raw = ('synthetic-unviewed-bytes-%d' % i).encode()
            sha = hashlib.sha256(raw).hexdigest()
            path = 'images/' + sha + '.jpg'
            posts = [{'post_id': str(2*i-1+n), 'images': [dict(media_index=1, path=path, sha256=sha)]}
                     for n in range(2)]
            jid = 'job-%02d' % i
            manifest = dict(dataset_version='synthetic-production', job_id=jid, split='production', posts=posts)
            bundle = self.bundle_dir / (jid + '.zip')
            with zipfile.ZipFile(bundle, 'w') as z:
                z.writestr('manifest.json', canonical(manifest))
                z.writestr(path, raw)
            source = dict(job_id=jid, asset=bundle.name, bytes=bundle.stat().st_size, sha256=digest(bundle),
                          manifest_sha256=hashlib.sha256(canonical(manifest)).hexdigest(),
                          post_ids=[p['post_id'] for p in posts], split='production')
            jobs.append(dict(job_id=jid, split='production', post_ids=source['post_ids'], manifest=manifest,
                             manifest_sha256=source['manifest_sha256'], sources=[source]))
        self.catalog = dict(dataset_version='synthetic-production', repository='unused/test', jobs=jobs,
                            screening=dict(state='complete', receipt_sha256='a'*64))
        atomic_write(self.root / 'data/catalog.json', canonical(self.catalog))
        atomic_write(self.root / 'data/assets.json', b'{}\n')
        self.remote = self.root / 'remote.git'
        subprocess.run(['git', 'init', '--bare', '--quiet', str(self.remote)], check=True)
        self.config = dict(run_id='synthetic-production', schema_version=contract_v4.VERSION,
            model_id='gpt-6.1-terra', reasoning_effort='high', remote=str(self.remote),
            catalog_path='data/catalog.json', catalog_sha256=digest(self.root / 'data/catalog.json'),
            assets_path='data/assets.json', manual_path='docs/LABELING_V4_PRODUCTION.md',
            manual_sha256=digest(self.root / 'docs/LABELING_V4_PRODUCTION.md'),
            contract_sha256=digest(self.root / 'pipeline_production/contract_v4.py'),
            toolchain_sha256=fingerprint(self.root), exclusion_policy_path='data/exclusion.json',
            exclusion_policy_sha256=digest(self.root / 'data/exclusion.json'), screening_receipt_sha256='a'*64,
            job_ids=[j['job_id'] for j in jobs], split='production', max_workers=10, max_posts=24,
            worker_ids=['terra-prod-%02d' % i for i in range(1, 11)], batch_size=50, queue_version='dispatch-v1')
        self.path = self.root / 'runs/test.json'
        atomic_write(self.path, canonical(self.config))
        atomic_write(self.root / 'data/launch-control-production.json', canonical(dict(state='authorized',
            authorized_run_id=self.config['run_id'], run_config_sha256=hashlib.sha256(canonical(self.config)).hexdigest(),
            catalog_sha256=self.config['catalog_sha256'], screening_receipt_sha256='a'*64,
            max_workers=10, max_posts=24, authorization_note='Synthetic offline test only')))
        self.patch = patch('pipeline_production.worker.ROOT', self.root)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def call(self, command, **kw):
        args = SimpleNamespace(config=self.path, remote=None, command=command, job=None,
            worker=self.config['worker_ids'][0], bundle_dir=str(self.bundle_dir), input=None,
            post=None, reason='input_requires_review', context_action='summary', signal=None, media_index=None, query=None)
        for k, v in kw.items():
            setattr(args, k, v)
        out = io.StringIO()
        with redirect_stdout(out):
            worker.run(args)
        return json.loads(out.getvalue())

    def cli_claim(self, worker_id):
        code = 'from pathlib import Path; from pipeline_production import worker; worker.ROOT=Path(%r); worker.main()' % str(self.root)
        return subprocess.run([sys.executable, '-c', code, '--config', str(self.path), 'claim',
            '--worker', worker_id, '--bundle-dir', str(self.bundle_dir)], cwd=self.repo, capture_output=True, text=True)

    def test_ten_real_cli_processes_claim_disjoint_jobs(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            results = list(pool.map(self.cli_claim, self.config['worker_ids']))
        for r in results:
            self.assertEqual(r.returncode, 0, r.stderr)
        ids = [json.loads(r.stdout)['job_id'] for r in results]
        self.assertEqual(len(set(ids)), 10)
        self.assertEqual(self.call('status')['counts']['leased'], 10)

    def test_save_checkpoint_finish_collect_and_autonomous_next_job(self):
        first = self.call('claim')
        jid = first['job_id']
        folder = Path(first['folder'])
        manifest = read_json(folder / 'manifest.json')
        for post in manifest['posts']:
            self.call('next', job=jid)
            row = synthetic(post, worker.provenance(self.config, manifest), self.config['worker_ids'][0])
            atomic_write(folder / 'draft.json', canonical(row))
            self.call('save', job=jid)
        self.call('checkpoint', job=jid)
        self.call('finish', job=jid)
        with redirect_stdout(io.StringIO()):
            collect(self.path, self.root / 'output', remote=self.remote)
        self.assertEqual(read_json(self.root / 'output/receipt.json')['processed_posts'], 2)
        self.assertNotEqual(self.call('claim')['job_id'], jid)

    def test_existing_lease_rehydrates_after_lost_local_lease_file(self):
        first = self.call('claim')
        lease_path = Path(first['folder']) / 'lease.json'
        lease = read_json(lease_path)
        lease_path.unlink()
        resumed = self.call('claim')
        self.assertEqual(resumed['status'], 'active_job_exists')
        self.assertEqual(resumed['job_id'], first['job_id'])
        self.assertEqual(read_json(lease_path)['token'], lease['token'])

    def test_refusal_excludes_post_and_same_hash_before_any_path_is_returned(self):
        first = self.call('claim')
        jid = first['job_id']
        folder = Path(first['folder'])
        manifest = read_json(folder / 'manifest.json')
        p1, p2 = manifest['posts']
        self.call('exclude', job=jid, post=p1['post_id'], signal='image_tool_refusal', media_index=1)
        row = read_json(folder / 'results' / (p1['post_id'] + '.json'))
        self.assertTrue(disposition.is_exclusion(row))
        self.assertNotIn('images', row)
        result = self.call('next', job=jid)
        self.assertEqual(result['status'], 'known_refusal_requires_exclusion')
        self.assertEqual(result['post_id'], p2['post_id'])
        self.assertNotIn('images', result)

    def test_excluded_inputs_and_nonproduction_sources_rejected_before_extraction(self):
        job = self.catalog['jobs'][0]
        policy = dict(self.policy, post_ids=[job['post_ids'][0]])
        target = self.root / 'forbidden'
        with self.assertRaisesRegex(ValueError, 'Excluded'):
            prepare_job(self.catalog, job, target, {}, policy, bundle_dir=self.bundle_dir)
        self.assertFalse(target.exists())
        changed = copy.deepcopy(job)
        changed['manifest']['split'] = 'calibration'
        changed['manifest_sha256'] = hashlib.sha256(canonical(changed['manifest'])).hexdigest()
        with self.assertRaises(ValueError):
            prepare_job(self.catalog, changed, target, {}, self.policy, bundle_dir=self.bundle_dir)
        self.assertFalse(target.exists())

    def test_screened_subset_extracts_only_unchanged_selected_posts(self):
        subset = copy.deepcopy(self.catalog['jobs'][0])
        kept, omitted = subset['manifest']['posts']
        subset['manifest']['posts'] = [kept]
        subset['post_ids'] = [kept['post_id']]
        subset['manifest_sha256'] = hashlib.sha256(canonical(subset['manifest'])).hexdigest()
        target = self.root / 'subset'
        with self.assertRaisesRegex(ValueError, 'exact pinned job manifest'):
            prepare_job(self.catalog, subset, target, {}, self.policy, bundle_dir=self.bundle_dir)

        catalog = dict(self.catalog, subset_of_catalog_sha256='a' * 64)
        manifest = prepare_job(catalog, subset, target, {}, self.policy, bundle_dir=self.bundle_dir)
        self.assertEqual(manifest['posts'], [kept])
        images = {im['path'] for im in kept['images']}
        self.assertEqual({p.relative_to(target).as_posix() for p in target.rglob('*.jpg')}, images)
        self.assertNotEqual(omitted['post_id'], kept['post_id'])

        subset['manifest']['posts'][0] = dict(kept, images=[])
        subset['manifest_sha256'] = hashlib.sha256(canonical(subset['manifest'])).hexdigest()
        with self.assertRaisesRegex(ValueError, 'Subset differs from the screened source'):
            prepare_job(catalog, subset, self.root / 'tampered', {}, self.policy, bundle_dir=self.bundle_dir)

    def test_authorized_scope_and_contract_unchanged(self):
        self.assertEqual((self.repo / 'pipeline_production/contract_v4.py').read_bytes(),
                         (self.repo / 'pipeline_parallel/contract_v4.py').read_bytes())
        for key, value in [('max_workers', 11), ('batch_size', 51), ('model_id', 'other')]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                require_launch(dict(self.config, **{key: value}), self.catalog, self.root)
        with self.assertRaises(ValueError):
            self.call('claim', worker='unlisted-worker')
        atomic_write(self.root / 'data/launch-control-production.json', canonical({'state': 'blocked'}))
        with self.assertRaises(ValueError):
            self.call('claim')


if __name__ == '__main__':
    unittest.main()
