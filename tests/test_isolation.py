import copy
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from pipeline.bundles import unpack
from pipeline.common import canonical, atomic_write, digest, read_json
from pipeline.human_source import bundle_root
from pipeline.isolation import audit_workspace, check_catalog, check_post_files, load_policy, prepare_policy
from pipeline.screening import ScreeningStore
from pipeline.prepare_screened import build
from test_screening import source_fixture


class IsolationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)
        self.index=source_fixture(self.root)
        self.store=ScreeningStore(self.root/'private/screening/data-v1.sqlite3',self.index)
        s=self.store.apply(['1'],'exclude','other',0)
        s=self.store.apply(['3','4'],'include','',s['revision'])
        self.store.complete(s['revision'],'human_review_complete')
        self.catalog=build(self.root)
        path=prepare_policy(self.root,self.catalog)
        self.config={'exclusion_policy_path':path.relative_to(self.root).as_posix(),'exclusion_policy_sha256':digest(path),
                     'screening_receipt_sha256':self.catalog['screening']['receipt_sha256']}
        self.policy=load_policy(self.config,self.root)

    def tearDown(self):self.tmp.cleanup()

    def test_excluded_archive_is_rejected_before_any_image_is_written(self):
        job=read_json(self.root/'data/catalog.json')['jobs'][0]
        target=self.root/'worker-input'
        with self.assertRaisesRegex(ValueError,'Excluded'):
            unpack(self.root/'dist/data-v1'/job['asset'],job,target,exclusion_policy=self.policy)
        self.assertFalse(target.exists())
        with self.assertRaisesRegex(ValueError,'Excluded'):
            check_catalog(read_json(self.root/'data/catalog.json'),self.policy)

    def test_safe_input_passes_but_swapped_or_escaped_path_is_not_exposed(self):
        job=self.catalog['jobs'][0];target=self.root/'worker-input'
        manifest=unpack(self.root/'dist'/self.catalog['dataset_version']/job['asset'],job,target,exclusion_policy=self.policy)
        post=manifest['posts'][0]
        check_post_files(target,post,self.policy)
        (target/post['images'][0]['path']).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'bytes/path'):check_post_files(target,post,self.policy)
        bad=copy.deepcopy(post);bad['images'][0]['path']='../outside.jpg'
        with self.assertRaisesRegex(ValueError,'bytes/path'):check_post_files(target,bad,self.policy)

    def test_missing_or_changed_policy_and_receipt_fail_closed(self):
        with self.assertRaisesRegex(ValueError,'required'):load_policy({},self.root)
        path=self.root/self.config['exclusion_policy_path']
        atomic_write(path,canonical(dict(self.policy,post_ids=[])))
        with self.assertRaisesRegex(ValueError,'changed'):load_policy(self.config,self.root)
        receipt_path=self.root/'private/screening/screening-receipt.json'
        receipt=read_json(receipt_path);receipt['effective_excluded_ids']=[]
        atomic_write(receipt_path,canonical(receipt))
        with self.assertRaisesRegex(ValueError,'receipt mismatch'):prepare_policy(self.root,self.catalog)

    def test_cache_audit_detects_renamed_bytes_in_files_and_archives(self):
        cache=self.root/'cache';cache.mkdir()
        raw=b'synthetic image A'
        (cache/'innocent-name.jpg').write_bytes(raw)
        with self.assertRaisesRegex(ValueError,'Excluded image'):audit_workspace(cache,self.policy)
        (cache/'innocent-name.jpg').unlink()
        with zipfile.ZipFile(cache/'cached.zip','w') as z:z.writestr('renamed.jpg',raw)
        with self.assertRaisesRegex(ValueError,'archive'):audit_workspace(cache,self.policy)
        (cache/'cached.zip').unlink()
        self.assertEqual(audit_workspace(cache,self.policy)['excluded_images_found'],0)

    def test_human_archive_override_must_be_outside_workspace(self):
        path=self.root/'private/human-source.json'
        atomic_write(path,canonical({'version':1,'bundle_root':str(self.root/'dist/data-v1')}))
        with self.assertRaisesRegex(ValueError,'outside'):bundle_root(self.root)
        with tempfile.TemporaryDirectory() as external:
            atomic_write(path,canonical({'version':1,'bundle_root':external}))
            self.assertEqual(bundle_root(self.root),Path(external).resolve())
        with self.assertRaisesRegex(ValueError,'exist'):bundle_root(self.root)
