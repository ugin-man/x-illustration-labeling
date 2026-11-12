import concurrent.futures
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import zipfile

from pipeline_parallel.common import canonical,atomic_write,digest,read_json
from pipeline_parallel.bundles import prepare_job
from pipeline_parallel.git_queue import GitQueue,Conflict,ClaimBusy
from pipeline_parallel.launch_control import require_launch
from pipeline_parallel.toolchain import FILES,fingerprint
from pipeline_parallel import contract_v4


class ParallelRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.repo=Path(__file__).resolve().parents[1]
        for name in set(FILES)|{'docs/LABELING_V4_PARALLEL.md'}:
            dest=self.root/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(self.repo/name,dest)
        policy={'version':1,'screening_receipt_sha256':'a'*64,'post_ids':['999'],'image_sha256':['f'*64]}
        atomic_write(self.root/'data/exclusion.json',canonical(policy));self.policy=policy
        posts=[];payloads={}
        for n in range(1,7):
            raw=f'synthetic-image-{n}'.encode();sha=hashlib.sha256(raw).hexdigest();path='images/'+sha+'.jpg';payloads[path]=raw
            posts.append({'post_id':str(n),'images':[{'media_index':1,'path':path,'sha256':sha}]})
        original={'dataset_version':'screened-test','job_id':'source-cal','split':'calibration','posts':posts}
        self.bundle_dir=self.root/'bundles';self.bundle_dir.mkdir();bundle=self.bundle_dir/'source.zip'
        with zipfile.ZipFile(bundle,'w') as z:
            z.writestr('manifest.json',canonical(original))
            for path,raw in payloads.items():z.writestr(path,raw)
        source={'job_id':'source-cal','asset':'source.zip','bytes':bundle.stat().st_size,'sha256':digest(bundle),
                'manifest_sha256':hashlib.sha256(canonical(original)).hexdigest(),'post_ids':[p['post_id'] for p in posts],'split':'calibration'}
        jobs=[]
        for n,post in enumerate(posts,1):
            m={'dataset_version':'test-parallel','job_id':f'part-{n}','split':'calibration','posts':[post]}
            jobs.append({'job_id':m['job_id'],'split':'calibration','post_ids':[post['post_id']],'manifest':m,
                         'manifest_sha256':hashlib.sha256(canonical(m)).hexdigest(),'sources':[source]})
        catalog={'dataset_version':'test-parallel','repository':'unused/test','jobs':jobs,
                 'screening':{'state':'complete','receipt_sha256':'a'*64}}
        atomic_write(self.root/'data/catalog.json',canonical(catalog));atomic_write(self.root/'data/assets.json',b'{}\n')
        self.catalog=catalog
        self.remote=self.root/'remote.git';subprocess.run(['git','init','--bare','--quiet',str(self.remote)],check=True)
        config={'run_id':'parallel-test','schema_version':contract_v4.VERSION,'model_id':'gpt-6.1-terra','reasoning_effort':'high',
                'remote':str(self.remote),'catalog_path':'data/catalog.json','catalog_sha256':digest(self.root/'data/catalog.json'),
                'assets_path':'data/assets.json','manual_path':'docs/LABELING_V4_PARALLEL.md','manual_sha256':digest(self.root/'docs/LABELING_V4_PARALLEL.md'),
                'contract_sha256':digest(self.root/'pipeline_parallel/contract_v4.py'),'toolchain_sha256':fingerprint(self.root),
                'exclusion_policy_path':'data/exclusion.json','exclusion_policy_sha256':digest(self.root/'data/exclusion.json'),
                'screening_receipt_sha256':'a'*64,'job_ids':[j['job_id'] for j in jobs],'split':'calibration',
                'max_workers':3,'max_posts':6,'worker_ids':['terra-p3-01','terra-p3-02','terra-p3-03']}
        self.config=config;self.path=self.root/'runs/test.json';atomic_write(self.path,canonical(config))
        self.authorize()
    def authorize(self):
        atomic_write(self.root/'data/launch-control-parallel.json',canonical({'state':'authorized','authorized_run_id':self.config['run_id'],
            'run_config_sha256':hashlib.sha256(canonical(self.config)).hexdigest(),'catalog_sha256':self.config['catalog_sha256'],
            'screening_receipt_sha256':'a'*64,'max_workers':3,'max_posts':6,'authorization_note':'Synthetic test only'}))
    def tearDown(self):self.tmp.cleanup()
    def cli(self,worker):
        code="from pathlib import Path; from pipeline_parallel import worker; worker.ROOT=Path(%r); worker.main()" % str(self.root)
        return subprocess.run([sys.executable,'-c',code,'--config',str(self.path),'claim','--worker',worker,'--bundle-dir',str(self.bundle_dir)],cwd=self.repo,capture_output=True,text=True)
    def test_three_actual_cli_claims_get_distinct_jobs(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            results=list(pool.map(self.cli,self.config['worker_ids']))
        for r in results:self.assertEqual(r.returncode,0,r.stderr)
        ids=[json.loads(r.stdout)['job_id'] for r in results];self.assertEqual(len(set(ids)),3)
        for worker,jid in zip(self.config['worker_ids'],ids):
            again=self.cli(worker);self.assertEqual(again.returncode,0,again.stderr)
            self.assertEqual(json.loads(again.stdout)['job_id'],jid)
            self.assertEqual(json.loads(again.stdout)['status'],'active_job_exists')
        with GitQueue(self.remote,'parallel-test',self.config['catalog_sha256']) as q:
            active=[q.read(j)[1] for j in ids];self.assertEqual({s['worker_id'] for s in active},set(self.config['worker_ids']))
    def test_same_worker_concurrent_claims_cannot_acquire_two_jobs(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:results=list(pool.map(self.cli,['terra-p3-01']*3))
        for r in results:self.assertEqual(r.returncode,0,r.stderr)
        with GitQueue(self.remote,'parallel-test',self.config['catalog_sha256']) as q:
            research=set(q.heads())&set(self.config['job_ids']);self.assertEqual(len(research),1)
    def test_three_contenders_same_job_have_exactly_one_winner(self):
        barrier=threading.Barrier(3)
        def contend(n):
            with GitQueue(self.remote,'race','b'*64) as q:
                publish=q._publish
                def synced(*args):barrier.wait(timeout=20);return publish(*args)
                q._publish=synced
                try:return bool(q.reserve('one-job',f'worker-{n}'))
                except Conflict:return False
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:self.assertEqual(sum(pool.map(contend,range(3))),1)
    def test_unknown_worker_and_changed_scope_rejected(self):
        result=self.cli('fourth-worker');self.assertNotEqual(result.returncode,0)
        self.assertIn('three pinned',result.stderr)
        changed=copy.deepcopy(self.config);changed['max_workers']=4
        with self.assertRaises(ValueError):require_launch(changed,self.catalog,self.root)
        atomic_write(self.root/'data/launch-control-parallel.json',canonical({'state':'blocked'}))
        self.assertNotEqual(self.cli('terra-p3-01').returncode,0)
    def test_subset_extracts_only_its_own_images(self):
        job=self.catalog['jobs'][0];target=self.root/'subset'
        m=prepare_job(self.catalog,job,target,{},self.policy,bundle_dir=self.bundle_dir)
        self.assertEqual([p['post_id'] for p in m['posts']],['1'])
        self.assertEqual(len(list((target/'images').glob('*'))),1)
        changed=copy.deepcopy(job);changed['manifest']['posts'][0]['images'][0]['sha256']='0'*64
        changed['manifest_sha256']=hashlib.sha256(canonical(changed['manifest'])).hexdigest()
        with self.assertRaises(ValueError):prepare_job(self.catalog,changed,self.root/'bad',{},self.policy,bundle_dir=self.bundle_dir)
    def test_excluded_input_rejected_before_any_extraction(self):
        job=self.catalog['jobs'][0];target=self.root/'excluded';p=copy.deepcopy(self.policy);p['post_ids']=['1']
        with self.assertRaises(ValueError):prepare_job(self.catalog,job,target,{},p,bundle_dir=self.bundle_dir)
        self.assertFalse(target.exists())
    def test_classification_contract_has_no_changes(self):
        self.assertEqual((self.repo/'pipeline_v4/contract_v4.py').read_bytes(),(self.repo/'pipeline_parallel/contract_v4.py').read_bytes())


if __name__=='__main__':unittest.main()
