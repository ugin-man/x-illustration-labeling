"""Behavioral v4 regression tests. Synthetic data and temporary local Git only."""
import copy
from contextlib import redirect_stdout
import csv
import io
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from pipeline_v4 import contract_v4 as c,worker,disposition
from pipeline_v4.authoring import observed as o,unknown as u,na,new_character,new_appearance,record_complete_counts,link_characters
from pipeline_v4.common import atomic_write,canonical,read_json
from pipeline_v4.collect import collect,export,aggregate
from pipeline_v4.context import budget
from pipeline_v4.prepare_run import prepare
from pipeline_v4.toolchain import FILES
from pipeline_v4.isolation import check_manifest,check_post_files
from pipeline.prepare_screened import build
from pipeline.screening import ScreeningStore
from test_screening import source_fixture

def synthetic(post,prov,worker_id='terra-v4-01'):
    r=c.template(post,prov,worker_id);r['execution']['finished_at']=r['execution']['started_at']
    ch=new_character('c1','synthetic same individual across images')
    for im in r['images']:
        im.update(viewed=True,read_error=None)
        im['attributes']={
          'content_kind':o('illustration','synthetic drawing'),'illustration_present':o(True,'synthetic drawing'),
          'main_subject':o('person_or_animal','synthetic person'),'format':o('illustration','synthetic one drawing'),
          'technique':o('digital','synthetic default digital'),'coloring_state':o('colored','synthetic filled areas'),
          'color_presence':o('chromatic','synthetic red'),'background':o('none','synthetic blank'),
          'object_kind':na('no_objects'),'environment':na('no_environment'),'person_animal_presence':o(True,'synthetic person'),
          'object_count':o('other','synthetic no objects','no_objects'),'time_of_day':u('no_time_clues'),'design_kind':na('no_design'),
          **{'has_'+color+'_hair':o(color=='red','synthetic independently checked image hair') for color in c.COLORS}}
        ch['appearances'].append(new_appearance(im['media_index'],'synthetic center',
          entity_kind=o('person','synthetic human'),body_form=o('human_like','synthetic shape'),
          crop=o('waist_up','synthetic head to waist'),expression=o('neutral','synthetic neutral face'),
          hair_basis=o('colored_or_toned','synthetic red hair fill'),hair_colors=o(['red'],'synthetic hair'),
          gender_presentation=u('synthetic ambiguous presentation'),age_presentation=o('young_adult','synthetic adult appearance')))
    r['characters']=[ch];record_complete_counts(r,'synthetic single identity')
    r['post_attributes']['work_form']=o('single_illustration','synthetic one work')
    r['context'].update(state='complete',stop_reason='no_leads',attributes={'creation':u('synthetic no leads'),'promotion':o(False,'synthetic no promotion')})
    return r

class ContractV4Tests(unittest.TestCase):
    def setUp(self):
        self.post={'post_id':'123','images':[{'media_index':1,'sha256':'a'*64}]};self.prov={'test':'synthetic'}
        self.row=synthetic(self.post,self.prov)
    def valid(self,r=None):return c.validate(r or self.row,self.post,self.prov)
    def test_original_24_fields_and_required_values(self):
        original=json.loads((worker.ROOT/'review/original-question-definitions.json').read_text(encoding='utf-8'))
        self.assertEqual(set(c.QUESTION_MAP),{q['qid'] for q in original['questions']});self.valid()
        for scope,key in [('image','coloring_state'),('appearance','crop'),('appearance','expression')]:
            r=copy.deepcopy(self.row);attrs=r['images'][0]['attributes'] if scope=='image' else r['characters'][0]['appearances'][0]['attributes']
            del attrs[key]
            with self.subTest(key=key),self.assertRaises(AssertionError):self.valid(r)
    def test_subject_does_not_gate_other_fields(self):
        for subject in c.IMAGE_FIELDS['main_subject']:
            r=copy.deepcopy(self.row);a=r['images'][0]['attributes'];a['main_subject']=o(subject,'synthetic subject only','multiple themes' if subject=='other' else '')
            a['time_of_day']=o('night','synthetic independent time clue');self.valid(r)
    def test_mob_count_zero_preserves_presence_and_hair(self):
        r=self.row;r['characters'][0]['count_role']='background_extra';r['characters'][0]['observation_type']='group'
        record_complete_counts(r,'synthetic all human observations are clear background extras');self.valid()
        self.assertEqual(r['person_count']['value'],0);self.assertEqual(aggregate(r['images'],'person_animal_presence'),'true')
        self.assertEqual(aggregate(r['images'],'has_red_hair'),'true')
        r['images'][0]['attributes']['person_animal_presence']=o(False,'bad count-derived absence')
        with self.assertRaisesRegex(AssertionError,'Presence'):self.valid()
    def test_repeated_character_different_appearances_is_one(self):
        ch=self.row['characters'][0];app=copy.deepcopy(ch['appearances'][0]);app['location']='second panel';app['attributes']['expression']=o('smile','synthetic second expression');ch['appearances'].append(app)
        self.valid();self.assertEqual(self.row['character_count']['value'],1)
        self.row['character_count']=o(2,'incorrect panel count')
        with self.assertRaisesRegex(AssertionError,'unique'):self.valid()
    def test_no_twelve_character_truncation(self):
        original=self.row['characters'][0]
        self.row['characters']=[dict(copy.deepcopy(original),id='c'+str(i),grouping_evidence='synthetic distinct '+str(i)) for i in range(1,14)]
        record_complete_counts(self.row,'synthetic 13 distinct people');self.valid();self.assertEqual(self.row['person_count']['value'],13)
    def test_uncolored_paper_cannot_be_hair_color(self):
        a=self.row['characters'][0]['appearances'][0]['attributes'];a['hair_basis']=o('uncolored','synthetic unfilled hair')
        a['hair_colors']=o(['white'],'incorrect paper color');self.row['images'][0]['attributes']['has_white_hair']=o(True,'incorrect')
        with self.assertRaisesRegex(AssertionError,'Uncolored'):self.valid()
        a['hair_colors']=u('uncolored_hair')
        for color in c.COLORS:self.row['images'][0]['attributes']['has_'+color+'_hair']=u('uncolored_hair')
        self.row['images'][0]['attributes']['coloring_state']=o('line_art','synthetic line drawing');self.valid()
    def test_line_art_with_actual_black_hair_fill_keeps_black(self):
        a=self.row['characters'][0]['appearances'][0]['attributes'];a['hair_colors']=o(['black'],'synthetic actual black hair fill')
        ia=self.row['images'][0]['attributes'];ia['coloring_state']=o('line_art','synthetic primarily line drawing')
        for color in c.COLORS:ia['has_'+color+'_hair']=o(color=='black','synthetic checked')
        self.valid()
    def test_no_environment_does_not_block_independent_time(self):
        a=self.row['images'][0]['attributes'];a['time_of_day']=o('night','synthetic explicit night cue');self.valid()
        a['environment']=o('nature','invented from blank background')
        with self.assertRaisesRegex(AssertionError,'environment'):self.valid()
    def test_humanoid_robot_keeps_attributes_not_person_count(self):
        a=self.row['characters'][0]['appearances'][0]['attributes'];a['entity_kind']=o('other','synthetic clear robot','robot')
        self.row['images'][0]['attributes']['person_animal_presence']=o(False,'synthetic only robot')
        record_complete_counts(self.row,'synthetic one robot');self.valid()
        self.assertEqual(self.row['person_count']['value'],0);self.assertEqual(self.row['character_count']['value'],1)
        a['crop']=na('wrong omission due to robot category')
        with self.assertRaises(AssertionError):self.valid()
    def test_anthropomorphic_animal_is_still_animal(self):
        app=new_appearance(1,'synthetic clothed cat',entity_kind=o('animal','synthetic cat'),body_form=o('human_like','synthetic bipedal body'),
          expression=o('smile','synthetic face'),hair_basis=o('no_hair','synthetic fur not hair'),
          animal_kind=o('real','synthetic cat species'),animal_style=o('anthropomorphic','synthetic human clothing'),animal_range=o('full_body','synthetic full cat'))
        self.row['characters'][0]['appearances']=[app]
        for color in c.COLORS:self.row['images'][0]['attributes']['has_'+color+'_hair']=o(False,'synthetic no hair')
        record_complete_counts(self.row,'synthetic one animal');self.valid()
        self.assertEqual(self.row['animal_count']['value'],1);self.assertEqual(self.row['person_count']['value'],0)
    def test_unknown_role_cannot_be_exact_count(self):
        self.row['characters'][0]['count_role']='uncertain';self.row['character_coverage']='partial'
        with self.assertRaisesRegex(AssertionError,'count'):self.valid()
        for k in c.COUNT_FIELDS:self.row[k]=u('role_uncertain')
        self.valid()
    def test_pending_is_not_unknown(self):
        self.row['images'][0]['attributes']['coloring_state']=c.answer()
        with self.assertRaisesRegex(AssertionError,'not assessed'):self.valid()
    def test_search_budget_counts_queries_and_deadline(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'budget.json'
            with self.assertRaises(ValueError):budget(p,'search',clock=lambda:0)
            self.assertTrue(budget(p,'search',clock=lambda:0,query='query 1')['permitted'])
            self.assertTrue(budget(p,'search',clock=lambda:1,query='query 2')['permitted'])
            self.assertFalse(budget(p,'search',clock=lambda:2,query='query 3')['permitted'])
            self.assertFalse(budget(p,'page',clock=lambda:60)['permitted'])
            self.assertEqual(len(read_json(p)['queries']),2)
    def test_csv_preserves_states_and_all_units(self):
        with tempfile.TemporaryDirectory() as d:
            export(d,[self.row])
            with (Path(d)/'answers.csv').open(encoding='utf-8-sig',newline='') as f:answers=list(csv.DictReader(f))
            fields={(r['unit'],r['field']) for r in answers}
            self.assertTrue({('image',f) for f in c.IMAGE_FIELDS}<=fields)
            self.assertTrue({('appearance',f) for f in c.APPEARANCE_FIELDS}<=fields)
            self.assertTrue({('post',f) for f in [*c.POST_FIELDS,*c.COUNT_FIELDS,*c.CONTEXT_FIELDS]}<=fields)
            self.assertEqual(next(r for r in answers if r['field']=='environment')['status'],'not_applicable')
    @unittest.skipUnless(shutil.which('node'),'Optional UI render check needs Node; Python/Git tests remain offline')
    def test_review_renderer_exposes_all_required_fields_and_states(self):
        result=subprocess.run(['node',str(worker.ROOT/'tests/check_v4_review_render.js')],input=json.dumps({'record':self.row,'expectedImage':list(c.IMAGE_FIELDS),'expectedAppearance':list(c.APPEARANCE_FIELDS)}),text=True,capture_output=True,cwd=worker.ROOT)
        self.assertEqual(result.returncode,0,result.stderr)
    def test_applicable_post_fields_cannot_be_hidden_as_not_applicable(self):
        for field in ['creation','promotion']:
            r=copy.deepcopy(self.row);r['context']['attributes'][field]=na('incorrect omission')
            with self.subTest(field=field),self.assertRaisesRegex(AssertionError,'Illustrated posts'):self.valid(r)

class RuntimeV4Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        for name in set(FILES)|{'docs/LABELING_V4.md'}:
            dest=self.root/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(worker.ROOT/name,dest)
        index=source_fixture(self.root);self.store=ScreeningStore(self.root/'private/screening/data-v1.sqlite3',index)
        s=self.store.apply(['1','2','3','4'],'include','',0);self.store.complete(s['revision'],'human_review_complete')
        with redirect_stdout(io.StringIO()):self.catalog=build(self.root);self.config=prepare('synthetic-v4','calibration',root=self.root)
        self.config['job_ids']=[self.catalog['jobs'][0]['job_id']];self.path=self.root/'runs/synthetic-v4.json';atomic_write(self.path,canonical(self.config))
        atomic_write(self.root/'data/launch-control-v4.json',canonical({'state':'authorized','authorized_run_id':'synthetic-v4','run_config_sha256':hashlib.sha256(canonical(self.config)).hexdigest(),'catalog_sha256':self.config['catalog_sha256'],'screening_receipt_sha256':self.config['screening_receipt_sha256'],'authorization_note':'Synthetic offline test only'}))
        self.remote=self.root/'remote.git';subprocess.run(['git','init','--bare','--quiet',str(self.remote)],check=True)
        self.root_patch=patch('pipeline_v4.worker.ROOT',self.root);self.root_patch.start()
        self.jid=self.config['job_ids'][0];self.folder=self.root/'.runtime/synthetic-v4'/self.jid
    def tearDown(self):self.root_patch.stop();self.tmp.cleanup()
    def call(self,command,**kw):
        args=SimpleNamespace(config=self.path,remote=str(self.remote),command=command,job=self.jid,worker='terra-v4-01',bundle_dir=str(self.root/'dist'/self.catalog['dataset_version']),input=None,post=None,reason='input_requires_review',context_action='summary',signal=None,media_index=None,query=None)
        for k,v in kw.items():setattr(args,k,v)
        out=io.StringIO()
        with redirect_stdout(out):worker.run(args)
        return json.loads(out.getvalue())
    def test_full_claim_save_checkpoint_finish_collect(self):
        self.assertEqual(self.call('claim')['job_id'],self.jid)
        self.assertEqual(self.call('claim')['status'],'active_job_exists')
        manifest=read_json(self.folder/'manifest.json')
        for post in manifest['posts']:
            self.call('next');r=synthetic(post,worker.provenance(self.config,manifest));atomic_write(self.folder/'draft.json',canonical(r))
            self.assertTrue(self.call('validate')['valid']);self.call('save')
        self.call('checkpoint');self.call('finish')
        with redirect_stdout(io.StringIO()):collect(self.path,self.root/'output',remote=self.remote)
        receipt=read_json(self.root/'output/receipt.json');self.assertEqual(receipt['processed_posts'],2)
        self.assertEqual(self.call('claim')['status'],'no_available_job')
    def test_only_pinned_worker_and_launch_block_fail_closed(self):
        with patch('pipeline_v4.worker.GitQueue') as network:
            with self.assertRaisesRegex(ValueError,'single worker'):self.call('claim',worker='another-worker')
            atomic_write(self.root/'data/launch-control-v4.json',canonical({'state':'blocked'}))
            for cmd in ['claim','next','save','checkpoint','finish','context']:
                with self.assertRaisesRegex(ValueError,'停止中'):self.call(cmd)
            network.assert_not_called()
    def test_policy_refusal_is_metadata_only_and_next_skips(self):
        self.call('claim');manifest=read_json(self.folder/'manifest.json');post=manifest['posts'][0]
        result=self.call('exclude',post=post['post_id'],signal='image_tool_refusal',media_index=1)
        self.assertTrue(result['temporary']);saved=read_json(self.folder/'results'/(post['post_id']+'.json'))
        self.assertTrue(disposition.is_exclusion(saved));self.assertNotIn('images',saved)
        self.assertNotEqual(self.call('next')['post_id'],post['post_id'])
    def test_prior_exclusion_and_tampered_bytes_rejected(self):
        self.call('claim');manifest=read_json(self.folder/'manifest.json');post=manifest['posts'][0]
        policy={'post_ids':[post['post_id']],'image_sha256':[]}
        with self.assertRaisesRegex(ValueError,'Excluded'):check_manifest(manifest,policy)
        policy={'post_ids':[],'image_sha256':[post['images'][0]['sha256']]}
        with self.assertRaisesRegex(ValueError,'Excluded'):check_post_files(self.folder,post,policy)
        image=self.folder/post['images'][0]['path'];image.write_bytes(b'tampered synthetic bytes')
        with self.assertRaisesRegex(ValueError,'bytes'):check_post_files(self.folder,post,{'post_ids':[],'image_sha256':[]})
    def test_authorization_pins_scope_and_model(self):
        for key,value in [('worker_id','different'),('model_id','different'),('split','production')]:
            with self.subTest(key=key):
                changed=dict(self.config,**{key:value})
                from pipeline_v4.launch_control import require_launch
                with self.assertRaisesRegex(ValueError,'scope/model/job'):require_launch(changed,self.catalog,self.root)
