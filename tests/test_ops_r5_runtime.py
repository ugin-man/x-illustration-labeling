"""Exercise the real r4 CLI using the existing synthetic local fixture."""
import hashlib
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch

import test_ops_r3_runtime as fixture
from pipeline_production.common import atomic_write, canonical, digest, read_json
from pipeline_production.git_queue import Conflict


class ReconciliationTests(unittest.TestCase):
    call=fixture.OpsRuntimeTests.call
    claimed=fixture.OpsRuntimeTests.claimed
    answer=fixture.OpsRuntimeTests.answer

    def setUp(self):
        fixture.OpsRuntimeTests.setUp(self)
        from ops_runtime_r5 import worker
        self.ops_worker=worker
        self.r4patch=patch('ops_runtime_r5.worker.ROOT',self.root);self.r4patch.start()
        hashes={}
        for source in (self.repo/'ops_runtime_r5').glob('*.py'):
            name=source.relative_to(self.repo).as_posix();dest=self.root/name
            dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,dest);hashes[name]=digest(dest)
        name='docs/WORKER_OPERATIONS_R5.md';shutil.copyfile(self.repo/name,self.root/name);hashes[name]=digest(self.root/name)
        m=dict(self.ops_manifest,operations_revision='ops-r5',files_sha256=hashes)
        mp=self.root/'ops/revisions/production-v4-001-ops-r5.json';atomic_write(mp,canonical(m))
        atomic_write(self.root/'ops/ops-r5-control.json',canonical(dict(state='enabled',operations_revision='ops-r5',base_run_id=self.config['run_id'],manifest_sha256=digest(mp),upgraded_worker_ids=self.config['worker_ids'],coordinator_ids=['ops-coordinator'])))

    def tearDown(self):
        self.r4patch.stop();fixture.OpsRuntimeTests.tearDown(self)

    def saved(self, checkpoint=False):
        jid,folder,manifest=self.claimed();post=manifest['posts'][0]
        row=self.answer(manifest,post);atomic_write(folder/'draft.json',canonical(row))
        self.call('save',job=jid)
        if checkpoint:self.call('checkpoint',job=jid)
        return jid,folder,manifest,post,row

    def test_stale_count_is_reconciled_by_exact_ids_and_bytes(self):
        jid,folder,manifest,post,row=self.saved(True)
        lease=read_json(folder/'lease.json');lease['completed_posts']=[];atomic_write(folder/'lease.json',canonical(lease))
        r=self.call('reconcile',job=jid)
        self.assertEqual(r['remote_accepted_count'],1);self.assertEqual(r['exact_matches'],1)
        self.assertEqual(r['local_unaccepted_ids'],[])
        self.assertEqual(read_json(folder/'lease.json')['completed_posts'],[post['post_id']])

    def test_unsubmitted_bytes_survive_reconciliation_and_checkpoint(self):
        jid,folder,manifest,post,row=self.saved(False);p=folder/'results'/(post['post_id']+'.json');old=p.read_bytes()
        r=self.call('reconcile',job=jid)
        self.assertEqual(r['local_unaccepted_ids'],[post['post_id']]);self.assertEqual(p.read_bytes(),old)
        self.call('checkpoint',job=jid);self.assertEqual(self.call('reconcile',job=jid)['exact_matches'],1)

    def test_missing_accepted_copy_is_restored_without_reclassification(self):
        jid,folder,manifest,post,row=self.saved(True);p=folder/'results'/(post['post_id']+'.json');old=p.read_bytes();p.unlink()
        r=self.call('reconcile',job=jid)
        self.assertEqual(r['restored_accepted_ids'],[post['post_id']]);self.assertEqual(p.read_bytes(),old)

    def test_real_conflict_preserves_both_and_does_not_overwrite(self):
        jid,folder,manifest,post,row=self.saved(True);p=folder/'results'/(post['post_id']+'.json')
        row['review_flags']=['different local metadata'];changed=canonical(row);atomic_write(p,changed)
        with self.assertRaisesRegex(Conflict,'byte mismatch'):self.call('reconcile',job=jid)
        self.assertEqual(p.read_bytes(),changed)
        from ops_runtime_r5.queue import OpsQueue
        with OpsQueue(self.remote,self.config['run_id'],self.config['catalog_sha256'],self.catalog['jobs'],self.config['worker_ids']) as q:
            h,s=q.read(jid);self.assertNotEqual(q.git('show',h+':post-'+post['post_id']+'.json').stdout,changed)

    def test_save_of_identical_accepted_result_is_idempotent_but_changes_fail(self):
        jid,folder,manifest,post,row=self.saved(True)
        r=self.call('save',job=jid);self.assertEqual(r['already_accepted'],post['post_id'])
        row['review_flags']=['changed'];atomic_write(folder/'draft.json',canonical(row))
        with self.assertRaisesRegex(Conflict,'immutable'):self.call('save',job=jid)


if __name__=='__main__':unittest.main()
