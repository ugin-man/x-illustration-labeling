import copy
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from pipeline import contract_v3 as c
from pipeline.collect import aggregate_person_or_animal
from pipeline.worker import run, ROOT


def two_characters():
    post={'post_id':'123','images':[{'media_index':1,'sha256':'a'*64},{'media_index':2,'sha256':'b'*64}]}
    r=c.template(post,{'run_id':'synthetic'},'test-only')
    r['execution']['finished_at']=r['execution']['started_at']
    for im in r['images']:
        im.update(viewed=True,attributes={k:c.answer('unknown',reason='synthetic') for k in c.IMAGE_FIELDS},character_ids=['c1','c2'])
    for i in range(1,3):
        r['characters'].append({'id':f'c{i}','grouping_evidence':'Same character repeated across panels and images (synthetic fixture)',
            'attributes':{'body_form':c.answer('observed','human_like','','synthetic')},
            'appearances':[{'media_index':m,'location':'All panels, '+str(i),'hair_colors':c.answer('unknown',reason='synthetic')} for m in (1,2)]})
    r['character_count']=c.answer('observed',2,'','Two unique identities')
    r['character_coverage']='complete'
    r['context'].update(state='complete',stop_reason='no_leads',attributes={'creation':c.answer('unknown',reason='synthetic_no_leads')})
    return post,r


class CompactSchemaTests(unittest.TestCase):
    def test_main_subject_is_required_and_separate_from_character_presence(self):
        p,r=two_characters()
        for subject in ('person_or_animal','object','landscape','design','other'):
            r['images'][0]['attributes']['main_subject']=c.answer('observed',subject,'','synthetic central theme')
            c.validate(r,p,{'run_id':'synthetic'})
            self.assertEqual(aggregate_person_or_animal(r),'true')
        del r['images'][0]['attributes']['main_subject']
        with self.assertRaises(AssertionError):c.validate(r,p,{'run_id':'synthetic'})
        r['images'][0]['attributes']['main_subject']=c.answer('not_applicable',reason='incorrectly omitted')
        r['images'][0]['attributes']['content_kind']=c.answer('observed','illustration','','synthetic illustration')
        with self.assertRaisesRegex(AssertionError,'main subject'):c.validate(r,p,{'run_id':'synthetic'})

    def test_background_measures_detail_and_rejects_old_location_types(self):
        p,r=two_characters()
        for value in ('none','solid_color','simple','detailed','other'):
            r['images'][0]['attributes']['background']=c.answer('observed',value,'','synthetic background detail')
            c.validate(r,p,{'run_id':'synthetic'})
        for value in ('abstract_decorative','environment','interior','mixed'):
            r['images'][0]['attributes']['background']=c.answer('observed',value,'','obsolete category')
            with self.subTest(value=value),self.assertRaises(AssertionError):c.validate(r,p,{'run_id':'synthetic'})

    def test_creation_uses_original_derivative_other_or_unknown_with_sources(self):
        p,r=two_characters()
        source={'url':'https://example.com/synthetic-source','accessed_at':r['execution']['started_at'],'kind':'external_source'}
        r['context']['stop_reason']='evidence_sufficient'
        for value in ('original','derivative','other'):
            a=c.answer('observed',value,'','synthetic provenance evidence');a['sources']=[source]
            r['context']['attributes']['creation']=a
            c.validate(r,p,{'run_id':'synthetic'})
        for value in ('official','mixed'):
            r['context']['attributes']['creation']['value']=value
            with self.subTest(value=value),self.assertRaises(AssertionError):c.validate(r,p,{'run_id':'synthetic'})
        r['context']['attributes']['creation']=c.answer('observed','other','','synthetic mixed origins without source')
        with self.assertRaises(AssertionError):c.validate(r,p,{'run_id':'synthetic'})
        r['context']['attributes']['creation']=c.answer('unknown',reason='insufficient evidence')
        r['context']['stop_reason']='no_leads'
        c.validate(r,p,{'run_id':'synthetic'})

    def test_mixed_is_not_an_image_category(self):
        p,base=two_characters()
        for field in ('main_subject','content_kind','format'):
            r=copy.deepcopy(base)
            r['images'][0]['attributes'][field]=c.answer('observed','other','','synthetic known combination with no dominant type')
            c.validate(r,p,{'run_id':'synthetic'})
            r['images'][0]['attributes'][field]['value']='mixed'
            with self.subTest(field=field),self.assertRaises(AssertionError):c.validate(r,p,{'run_id':'synthetic'})

    def test_presence_does_not_turn_incomplete_or_unknown_characters_into_absence(self):
        p,r=two_characters()
        r['character_coverage']='partial'
        self.assertEqual(aggregate_person_or_animal(r),'true')
        for char in r['characters']:char['attributes']['body_form']=c.answer('observed','other','','synthetic object character')
        self.assertEqual(aggregate_person_or_animal(r),'unknown')
        r['character_coverage']='complete'
        self.assertEqual(aggregate_person_or_animal(r),'false')
        r['characters'][0]['attributes']['body_form']=c.answer('unknown',reason='unclear form')
        self.assertEqual(aggregate_person_or_animal(r),'unknown')
        r['characters']=[]
        r['character_count']=c.answer('observed',0,'','synthetic empty scene')
        self.assertEqual(aggregate_person_or_animal(r),'false')
        r['images'][0]['viewed']=False
        self.assertEqual(aggregate_person_or_animal(r),'unknown')

    def test_crop_has_fixed_chest_and_waist_options(self):
        p,r=two_characters()
        for value in ('face','bust','waist_up','full_body','other_partial'):
            r['characters'][0]['attributes']['crop']=c.answer('observed',[value],'','synthetic visible extent')
            c.validate(r,p,{'run_id':'synthetic'})
        r['characters'][0]['attributes']['crop']=c.answer('unknown',reason='chest or waist boundary is hidden')
        c.validate(r,p,{'run_id':'synthetic'})
        for value in ('upper_body','knee_up'):
            r['characters'][0]['attributes']['crop']=c.answer('observed',[value],'','unsupported category')
            with self.subTest(value=value),self.assertRaises(AssertionError):c.validate(r,p,{'run_id':'synthetic'})

    def test_technique_is_required_with_two_values_or_unknown(self):
        p,r=two_characters()
        for value in ('digital','analog'):
            r['images'][0]['attributes']['technique']=c.answer('observed',value,'','synthetic visual estimate')
            c.validate(r,p,{'run_id':'synthetic'})
        r['images'][0]['attributes']['technique']=c.answer('unknown',reason='cannot distinguish or mixed methods')
        c.validate(r,p,{'run_id':'synthetic'})
        r['images'][0]['attributes']['technique']=c.answer('observed','mixed','','synthetic')
        with self.assertRaises(AssertionError):c.validate(r,p,{'run_id':'synthetic'})
        del r['images'][0]['attributes']['technique']
        with self.assertRaises(AssertionError):c.validate(r,p,{'run_id':'synthetic'})

    def test_same_characters_across_panels_and_images_count_once(self):
        p,r=two_characters();c.validate(r,p,{'run_id':'synthetic'})
        r['character_count']['value']=6
        with self.assertRaises(AssertionError):c.validate(r,p,{'run_id':'synthetic'})

    def test_rejects_old_or_invented_fields_colors_and_ranges(self):
        p,base=two_characters()
        variants=[]
        r=copy.deepcopy(base);r['images'][0]['attributes']['color_presence']=c.answer('observed','limited_palette','','synthetic');variants.append(r)
        r=copy.deepcopy(base);r['characters'][0]['attributes']['style']=c.answer('observed','stylized','','synthetic');variants.append(r)
        r=copy.deepcopy(base);r['characters'][0]['attributes']['crop']=c.answer('observed',['waist'],'','synthetic');variants.append(r)
        r=copy.deepcopy(base);r['characters'][0]['appearances'].append(copy.deepcopy(r['characters'][0]['appearances'][0]));variants.append(r)
        for r in variants:
            with self.assertRaises(AssertionError):c.validate(r,p,{'run_id':'synthetic'})

    def test_links_hair_presence_and_image_coverage_are_enforced(self):
        p,r=two_characters();r['images'][0]['character_ids']=['c1']
        with self.assertRaises(AssertionError):c.validate(r,p,{'run_id':'synthetic'})
        p,r=two_characters();r['characters'][0]['appearances'][0]['hair_colors']=c.answer('observed',['red'],'','synthetic')
        with self.assertRaises(AssertionError):c.validate(r,p,{'run_id':'synthetic'})
        r['images'][0]['attributes']['has_red_hair']=c.answer('observed',True,'','synthetic');c.validate(r,p,{'run_id':'synthetic'})
        r['images'].pop()
        with self.assertRaises(AssertionError):c.validate(r,p,{'run_id':'synthetic'})

    def test_incomplete_template_and_missing_optional_fields(self):
        p,r=two_characters();c.validate(r,p,{'run_id':'synthetic'})
        r['characters'][0]['attributes']['crop']=c.answer('observed',['bust','full_body'],'','synthetic distinct poses')
        c.validate(r,p,{'run_id':'synthetic'})
        with self.assertRaises((AssertionError,AttributeError,TypeError)):c.validate(c.template(p,{}),p,{})

    def test_blocked_claim_does_not_open_git_or_download_images(self):
        args=SimpleNamespace(config=ROOT/'runs/pilot-v2-001.json',remote=None,command='claim')
        with patch('pipeline.worker.GitQueue') as queue,patch('pipeline.worker.download') as download:
            with self.assertRaisesRegex(ValueError,'停止中'):run(args)
            queue.assert_not_called();download.assert_not_called()

    def test_unassessed_context_and_contradictory_status_are_rejected(self):
        p,base=two_characters()
        cases=[]
        r=copy.deepcopy(base);r['context']['state']='pending';cases.append(r)
        r=copy.deepcopy(base);r['context']['attributes']['creation']=c.answer('not_assessed',reason='pending');cases.append(r)
        r=copy.deepcopy(base);r['context']['state']='technical_failure';cases.append(r)
        r=copy.deepcopy(base);r['context']['stop_reason']='invented';cases.append(r)
        r=copy.deepcopy(base);r['context']['attributes']['creation']=c.answer('observed','original','','not found');cases.append(r)
        for r in cases:
            with self.subTest(context=r['context']):
                with self.assertRaises(AssertionError):c.validate(r,p,{'run_id':'synthetic'})
        p,r=two_characters()
        r['context'].update(state='technical_failure',stop_reason='tool_unavailable',attributes={'creation':c.answer('technical_failure',reason='no search tool')})
        c.validate(r,p,{'run_id':'synthetic'})

    def test_zero_characters_and_hairless_characters_cannot_have_positive_hair(self):
        p,r=two_characters()
        r.update(characters=[],character_count=c.answer('observed',0,'','no characters'))
        for im in r['images']:
            im['character_ids']=[]
            for color in c.COLORS:im['attributes']['has_'+color+'_hair']=c.answer('observed',False,'','no hair')
        c.validate(r,p,{'run_id':'synthetic'})
        r['images'][0]['attributes']['has_red_hair']=c.answer('observed',True,'','red')
        with self.assertRaisesRegex(AssertionError,'hair flags'):c.validate(r,p,{'run_id':'synthetic'})
        p,r=two_characters()
        for ch in r['characters']:
            for app in ch['appearances']:app['hair_colors']=c.answer('not_applicable',reason='no hair')
        with self.assertRaisesRegex(AssertionError,'hair flags'):c.validate(r,p,{'run_id':'synthetic'})

    def test_known_character_hair_sets_have_consistent_negative_flags(self):
        p,r=two_characters()
        for ch in r['characters']:
            for app in ch['appearances']:app['hair_colors']=c.answer('observed',['red'],'','visible red')
        for im in r['images']:
            for color in c.COLORS:im['attributes']['has_'+color+'_hair']=c.answer('observed',color=='red','','synthetic red hair only')
        c.validate(r,p,{'run_id':'synthetic'})
        r['images'][0]['attributes']['has_blue_hair']=c.answer('observed',True,'','contradiction')
        with self.assertRaises(AssertionError):c.validate(r,p,{'run_id':'synthetic'})
        r['character_coverage']='partial'
        c.validate(r,p,{'run_id':'synthetic'})  # Additional blue-haired character may lie beyond the detail cap.

    def test_unseen_image_prevents_full_count_and_duplicate_media_are_rejected(self):
        p,r=two_characters();p['images'][1]['media_index']=1
        with self.assertRaises(AssertionError):c.validate(r,p,{'run_id':'synthetic'})
        p,r=two_characters()
        r['characters']=[];r['character_coverage']='partial'
        for im in r['images']:
            im.update(viewed=False,read_error='synthetic failure',character_ids=[],attributes={k:c.answer('technical_failure',reason='unreadable') for k in c.IMAGE_FIELDS})
        with self.assertRaisesRegex(AssertionError,'Unseen'):c.validate(r,p,{'run_id':'synthetic'})
        r['character_count']=c.answer('unknown',reason='unseen images')
        c.validate(r,p,{'run_id':'synthetic'})
