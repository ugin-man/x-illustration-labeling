"""Offline integration: synthetic labels, temporary Git only, no research pixels/network."""
from contextlib import redirect_stdout
import csv
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

from pipeline import contract_v3 as c, worker, disposition
from pipeline.collect import collect
from pipeline.common import atomic_write, canonical, read_json
from pipeline.context import budget, fetch
from pipeline.git_queue import GitQueue, LostLease, QueueError
from pipeline.prepare_run import prepare
from pipeline.prepare_screened import build
from pipeline.screening import ScreeningStore
from pipeline.toolchain import FILES
from test_screening import source_fixture


def synthetic_answer(post, config, manifest, worker_id):
    r=c.template(post,worker.provenance(config,manifest),worker_id)
    r['execution']['finished_at']=r['execution']['started_at']
    for im in r['images']:
        im.update(viewed=True,character_ids=['c1'],attributes={k:c.answer('unknown',reason='synthetic_not_a_real_visual_assessment') for k in c.IMAGE_FIELDS})
        im['attributes']['main_subject']=c.answer('observed','design','','synthetic design with a character')
        im['attributes']['background']=c.answer('observed','simple','','synthetic few background marks')
    r['characters']=[{'id':'c1','grouping_evidence':'synthetic same character across images',
                      'attributes':{'body_form':c.answer('observed','human_like','','synthetic')},
                      'appearances':[{'media_index':i['media_index'],'location':'synthetic center','hair_colors':c.answer('unknown',reason='synthetic')} for i in post['images']]}]
    r.update(character_count=c.answer('observed',1,'','synthetic single identity'),character_coverage='complete')
    r['context'].update(state='complete',stop_reason='no_leads',attributes={'creation':c.answer('unknown',reason='synthetic no leads')})
    return r


class WorkerV3Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        for name in set(FILES)|{'pipeline/contract_v3.py','docs/LABELING_V3.md'}:
            dest=self.root/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(worker.ROOT/name,dest)
        self.index=source_fixture(self.root)
        self.store=ScreeningStore(self.root/'private/screening/data-v1.sqlite3',self.index)
        s=self.store.apply(['1','2','3','4'],'include','',0)
        self.store.complete(s['revision'],'human_review_complete')
        with redirect_stdout(io.StringIO()):
            self.catalog=build(self.root)
            self.config=prepare('synthetic-v3','calibration',root=self.root)
        self.config['job_ids']=[self.catalog['jobs'][0]['job_id']]
        self.path=self.root/'runs/synthetic-v3.json'
        atomic_write(self.path,canonical(self.config))
        atomic_write(self.root/'data/launch-control.json',canonical({'state':'authorized','authorized_run_id':'synthetic-v3',
            'catalog_sha256':self.config['catalog_sha256'],'screening_receipt_sha256':self.config['screening_receipt_sha256'],
            'authorization_note':'Synthetic offline test only; no real run authorized'}))
        self.remote=self.root/'remote.git'
        subprocess.run(['git','init','--bare','--quiet',str(self.remote)],check=True)
        self.root_patch=patch('pipeline.worker.ROOT',self.root);self.root_patch.start()
        self.jid=self.config['job_ids'][0];self.folder=self.root/'.runtime/synthetic-v3'/self.jid

    def tearDown(self):
        self.root_patch.stop();self.tmp.cleanup()

    def call(self, command, **kw):
        args=SimpleNamespace(config=self.path,remote=str(self.remote),command=command,job=self.jid,
                             worker='synthetic-worker',bundle_dir=str(self.root/'dist'/self.catalog['dataset_version']),
                             input=None,post=None,reason='input_requires_review',context_action='summary',signal=None,media_index=None)
        for k,v in kw.items():setattr(args,k,v)
        stream=io.StringIO()
        with redirect_stdout(stream):worker.run(args)
        return json.loads(stream.getvalue())

    def test_claim_resume_local_save_checkpoint_finish_collect(self):
        self.assertEqual(self.call('claim')['job_id'],self.jid)
        first=self.call('next')
        draft=read_json(self.folder/'draft.json');draft['review_flags']=['synthetic unfinished draft']
        atomic_write(self.folder/'draft.json',canonical(draft))
        self.assertTrue(self.call('next')['resumed_draft'])
        self.assertEqual(read_json(self.folder/'draft.json')['review_flags'],draft['review_flags'])
        manifest=read_json(self.folder/'manifest.json')
        for post in manifest['posts']:
            row=synthetic_answer(post,self.config,manifest,'synthetic-worker')
            atomic_write(self.folder/'draft.json',canonical(row))
            before=(self.folder/'draft.json').read_bytes()
            with patch('pipeline.worker.GitQueue') as network:
                self.assertFalse(self.call('validate')['saved'])
                self.assertFalse((self.folder/'results'/(post['post_id']+'.json')).exists())
                self.assertEqual((self.folder/'draft.json').read_bytes(),before)
                self.assertFalse(self.call('save')['remote_accepted'])
                network.assert_not_called()
        with self.assertRaises(QueueError):self.call('finish')
        lease=read_json(self.folder/'lease.json');lease['lease_until']=time.time()+5
        atomic_write(self.folder/'lease.json',canonical(lease))
        self.call('checkpoint')
        self.assertGreater(read_json(self.folder/'lease.json')['lease_until'],lease['lease_until']+3000)
        self.call('finish')
        with redirect_stdout(io.StringIO()):collect(self.path,self.root/'output',remote=self.remote)
        def table(name):
            with (self.root/'output'/name).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
        self.assertEqual([r['character_count'] for r in table('posts.csv')],['1','1'])
        self.assertEqual(len(table('characters.csv')),2)
        self.assertEqual(len(table('appearances.csv')),3)
        self.assertEqual(len(table('images.csv')),3)
        self.assertTrue(all(r['main_subject']=='design' and r['main_subject_status']=='observed' for r in table('images.csv')))
        self.assertTrue(all(r['background']=='simple' for r in table('images.csv')))
        self.assertTrue(all(r['has_person_or_animal']=='true' for r in table('posts.csv')))
        self.assertTrue(all(r['has_red_hair']=='unknown' for r in table('posts.csv')))
        self.assertEqual(read_json(self.root/'output/quality-profile.json')['units']['posts'],2)
        self.assertEqual(self.call('claim')['status'],'no_available_job')

    def test_expiry_and_human_edit_block_work_without_touching_remote(self):
        self.call('claim')
        lease=read_json(self.folder/'lease.json');lease['lease_until']=time.time()-1
        atomic_write(self.folder/'lease.json',canonical(lease))
        with patch('pipeline.worker.GitQueue') as network:
            with self.assertRaises(LostLease):self.call('next')
            network.assert_not_called()
        s=self.store.snapshot();self.store.apply(['1'],'hold','uncertain',s['revision'])
        with patch('pipeline.worker.GitQueue') as network:
            with self.assertRaisesRegex(ValueError,'decisions have changed'):self.call('claim')
            network.assert_not_called()
        # Cleanup still works even with missing input and now-revoked launch.
        (self.folder/'manifest.json').unlink()
        self.assertEqual(self.call('release')['status'],'release')

    def test_context_ledger_rejects_fabricated_work_and_cache_mixups(self):
        self.call('claim');self.call('next')
        manifest=read_json(self.folder/'manifest.json');post=manifest['posts'][0]
        row=synthetic_answer(post,self.config,manifest,'synthetic-worker')
        row['context']['searches']=1
        atomic_write(self.folder/'draft.json',canonical(row))
        with self.assertRaisesRegex(ValueError,'ledger'):self.call('validate')
        self.call('context',post=post['post_id'],context_action='search')
        row['context'].update(self.call('context',post=post['post_id'],context_action='summary'))
        atomic_write(self.folder/'draft.json',canonical(row))
        self.assertTrue(self.call('validate')['valid'])
        bad=json.loads(json.dumps(row));bad['context']['searches']=2
        atomic_write(self.folder/'results'/(post['post_id']+'.json'),canonical(bad))
        with self.assertRaisesRegex(ValueError,'ledger'):self.call('checkpoint')
        with self.assertRaisesRegex(ValueError,'not in'):self.call('context',post='999')
        cache=self.folder/'wrong-cache.json';atomic_write(cache,canonical({'post_id':'456','state':'available'}))
        with patch('pipeline.context.subprocess.run') as network:
            with self.assertRaisesRegex(ValueError,'another post'):fetch('123',cache)
            network.assert_not_called()

    def test_code_change_fails_closed_and_blocked_commands_do_not_use_git(self):
        atomic_write(self.root/'data/launch-control.json',canonical({'state':'blocked'}))
        with patch('pipeline.worker.GitQueue') as network,patch('pipeline.worker.download') as download:
            for command in ['claim','next','save','checkpoint','finish','context']:
                with self.subTest(command=command):
                    with self.assertRaisesRegex(ValueError,'停止中'):self.call(command)
            network.assert_not_called();download.assert_not_called()
        (self.root/'pipeline/context.py').write_text('# changed code',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'Worker code'):worker.check_config(self.path)

    def test_hold_stops_job_and_preserves_completed_local_results(self):
        self.call('claim');manifest=read_json(self.folder/'manifest.json')
        row=synthetic_answer(manifest['posts'][0],self.config,manifest,'synthetic-worker')
        atomic_write(self.folder/'draft.json',canonical(row));self.call('save')
        self.call('hold',post=manifest['posts'][1]['post_id'])
        self.assertEqual(self.call('status')['needs_review'],1)
        self.assertEqual(self.call('claim')['status'],'no_available_job')

    def test_new_screening_revision_keeps_frozen_catalog_and_requires_new_authorization(self):
        old_path=self.root/self.config['catalog_path'];old_bytes=old_path.read_bytes()
        s=self.store.snapshot();s=self.store.apply(['3'],'exclude','other',s['revision'])
        self.store.complete(s['revision'],'human_review_complete')
        with redirect_stdout(io.StringIO()):new=build(self.root)
        self.assertNotEqual(new['dataset_version'],self.catalog['dataset_version'])
        self.assertEqual(old_path.read_bytes(),old_bytes)
        worker.check_config(self.path)
        with self.assertRaisesRegex(ValueError,'decisions have changed'):self.call('claim')

    def test_policy_exclusion_skips_post_and_stays_out_of_research_tables(self):
        self.call('claim');self.call('next')
        manifest=read_json(self.folder/'manifest.json');first,second=manifest['posts']
        result=self.call('exclude',post=first['post_id'],signal='image_tool_refusal',media_index=1)
        self.assertEqual(result['next'],'next')
        excluded_path=self.folder/'results'/(first['post_id']+'.json')
        original=excluded_path.read_bytes()
        self.call('exclude',post=first['post_id'],signal='image_tool_refusal',media_index=1)
        self.assertEqual(original,excluded_path.read_bytes())
        # A resumed worker restores the minimal exclusion and never needs image pixels.
        excluded_path.unlink()
        with GitQueue(self.remote,self.config['run_id'],self.config['catalog_sha256']) as q:
            q.restore(self.jid,self.folder/'results')
        self.assertEqual(self.call('next')['post_id'],second['post_id'])
        with patch('pipeline.worker.context.fetch') as fetch_context:
            with self.assertRaisesRegex(ValueError,'excluded'):self.call('context',post=first['post_id'],context_action='fetch')
            fetch_context.assert_not_called()
        row=synthetic_answer(second,self.config,manifest,'synthetic-worker')
        atomic_write(self.folder/'draft.json',canonical(row));self.call('save');self.call('checkpoint');self.call('finish')
        with redirect_stdout(io.StringIO()):collect(self.path,self.root/'output',remote=self.remote)
        labels=[json.loads(s) for s in (self.root/'output/labels.jsonl').read_text(encoding='utf-8').splitlines()]
        exclusions=[json.loads(s) for s in (self.root/'output/exclusions.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertEqual([r['post_id'] for r in labels],[second['post_id']])
        self.assertEqual([r['post_id'] for r in exclusions],[first['post_id']])
        self.assertNotIn('images',exclusions[0]);self.assertNotIn('context',exclusions[0])
        receipt=read_json(self.root/'output/receipt.json')
        self.assertEqual((receipt['processed_posts'],receipt['excluded_posts'],receipt['resolved_posts']),(1,1,2))
        with (self.root/'output/posts.csv').open(encoding='utf-8-sig',newline='') as f:
            self.assertEqual([r['post_id'] for r in csv.DictReader(f)],[second['post_id']])

    def test_refusal_persists_before_network_failure_and_metadata_retry_is_safe(self):
        self.call('claim');manifest=read_json(self.folder/'manifest.json');first,second=manifest['posts']
        with patch('pipeline.worker.GitQueue.checkpoint',side_effect=QueueError('synthetic network failure')):
            with self.assertRaises(QueueError):self.call('exclude',post=first['post_id'],signal='model_refusal')
        saved=read_json(self.folder/'results'/(first['post_id']+'.json'))
        self.assertTrue(disposition.is_exclusion(saved))
        self.assertEqual(self.call('next')['post_id'],second['post_id'])
        self.call('exclude',post=first['post_id'],signal='model_refusal')
        self.assertEqual(read_json(self.folder/'results'/(first['post_id']+'.json')),saved)

    def test_exclusion_requires_real_signal_metadata_and_cannot_overwrite_labels(self):
        self.call('claim');manifest=read_json(self.folder/'manifest.json');post=manifest['posts'][0]
        with self.assertRaises(ValueError):self.call('exclude',post=post['post_id'])
        with self.assertRaises(ValueError):self.call('exclude',post='999',signal='model_refusal')
        with self.assertRaises(AssertionError):self.call('exclude',post=post['post_id'],signal='model_refusal',media_index=999)
        row=disposition.create(post,worker.provenance(self.config,manifest),'synthetic-worker','model_refusal')
        row['description']='forbidden extra field'
        with self.assertRaises(AssertionError):disposition.validate(row,post,worker.provenance(self.config,manifest))
        atomic_write(self.folder/'draft.json',canonical(synthetic_answer(post,self.config,manifest,'synthetic-worker')))
        self.call('save')
        from pipeline.git_queue import Conflict
        with self.assertRaises(Conflict):self.call('exclude',post=post['post_id'],signal='model_refusal')

    def test_all_excluded_job_completes_without_fabricated_labels(self):
        self.call('claim');manifest=read_json(self.folder/'manifest.json')
        for p in manifest['posts']:self.call('exclude',post=p['post_id'],signal='model_refusal')
        self.assertEqual(self.call('next')['status'],'local_batch_complete')
        self.call('finish')
        with redirect_stdout(io.StringIO()):collect(self.path,self.root/'output',remote=self.remote)
        self.assertEqual((self.root/'output/labels.jsonl').read_bytes(),b'')
        receipt=read_json(self.root/'output/receipt.json')
        self.assertEqual((receipt['processed_posts'],receipt['excluded_posts']),(0,2))

    def test_exclusion_cleanup_does_not_authorize_next_post(self):
        self.call('claim');manifest=read_json(self.folder/'manifest.json')
        atomic_write(self.root/'data/launch-control.json',canonical({'state':'blocked'}))
        self.call('exclude',post=manifest['posts'][0]['post_id'],signal='model_refusal')
        with self.assertRaisesRegex(ValueError,'停止中'):self.call('next')
