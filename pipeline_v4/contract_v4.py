"""Approved v4: all original questions, independent subject, unique IDs, mandatory appearances."""
from datetime import datetime, timezone
import math
import re
from urllib.parse import urlsplit

VERSION='v4-1'
COLORS='black brown blond_yellow red orange pink purple blue green white gray other'.split()
IMAGE_FIELDS={
 'content_kind':'illustration photo screenshot other'.split(),
 'illustration_present':'boolean',
 'main_subject':'person_or_animal object landscape design other'.split(),
 'format':'illustration comic design other'.split(),
 'technique':'digital analog'.split(),
 'coloring_state':'colored partially_colored line_art other'.split(),
 'color_presence':'chromatic achromatic'.split(),
 'background':'none solid_color simple detailed other'.split(),
 'object_kind':'real fictional other'.split(),
 'environment':'nature city interior fictional other'.split(),
 'person_animal_presence':'boolean',
 'object_count':'single multiple other'.split(),
 'time_of_day':'morning daytime night other'.split(),
 'design_kind':'text logo poster pattern decoration other'.split(),
 **{'has_'+c+'_hair':'boolean' for c in COLORS},
}
APPEARANCE_FIELDS={
 'entity_kind':'person animal other'.split(),
 'body_form':'human_like animal_like other'.split(),
 'gender_presentation':'male female multiple other'.split(),
 'crop':'face bust waist_up full_body other'.split(),
 'expression':'smile neutral anger sadness other'.split(),
 'hair_basis':'colored_or_toned uncolored no_hair uncertain'.split(),
 'hair_colors':['set',*COLORS],
 'age_presentation':'child young_adult elderly other'.split(),
 'animal_kind':'real fictional other'.split(),
 'animal_style':'deformed realistic anthropomorphic other'.split(),
 'animal_range':'full_body face partial other'.split(),
}
POST_FIELDS={'work_form':'single_illustration comic multiple_illustrations other'.split()}
CONTEXT_FIELDS={'creation':'original derivative other'.split(),'promotion':'boolean'}
CHARACTER_FIELDS={}
OPTIONAL_CHARACTER_FIELDS={}
COUNT_FIELDS=('character_count','person_count','animal_count')
STATES={'observed','unknown','not_applicable','not_assessed','technical_failure'}
QUESTION_MAP={
 'purpose':'image.main_subject','method':'image.technique','form':'post.work_form',
 'promo':'context.promotion','color':'image.coloring_state','creation':'context.creation',
 'bg':'image.background','n_persons':'person_count','n_animals':'animal_count',
 'person.gender':'appearance.gender_presentation','person.pose':'appearance.crop',
 'person.expr':'appearance.expression','person.hair':'appearance.hair_colors',
 'person.age':'appearance.age_presentation','animal.kind':'appearance.animal_kind',
 'animal.style':'appearance.animal_style','animal.range':'appearance.animal_range',
 'animal.expr':'appearance.expression','object.kind':'image.object_kind',
 'land.kind':'image.environment','land.beings':'image.person_animal_presence',
 'land.objects':'image.object_count','land.time':'image.time_of_day','design.kind':'image.design_kind',
}

def answer(status='not_assessed',value=None,reason='pending',evidence='',sources=None):
    return dict(status=status,value=value,reason=reason,evidence=evidence,sources=sources or [])

def validate_answer(a,spec):
    assert isinstance(a,dict) and set(a)=={'status','value','reason','evidence','sources'}, 'Answer shape differs'
    assert a['status'] in STATES and a['status']!='not_assessed', 'Required answer was not assessed'
    assert isinstance(a['reason'],str) and len(a['reason'])<=300
    assert isinstance(a['evidence'],str) and len(a['evidence'])<=600
    assert isinstance(a['sources'],list) and len(a['sources'])<=5
    for s in a['sources']:
        assert set(s)=={'url','accessed_at','kind'} and s['kind'] in {'post_text','external_source'}
        assert isinstance(s['url'],str) and len(s['url'])<=2000
        url=urlsplit(s['url'])
        assert url.scheme=='https' and url.hostname and not url.username and not url.password
        assert datetime.fromisoformat(s['accessed_at'].replace('Z','+00:00')).tzinfo
    if a['status']!='observed':
        assert a['value'] is None and a['reason'].strip(), 'Non-observed answers need a reason and no value'
        return
    assert a['evidence'].strip(), 'Observed answer needs visual/text evidence'
    v=a['value']
    if spec=='boolean':assert type(v) is bool
    elif spec=='integer':assert type(v) is int and v>=0
    elif spec[0]=='set':assert isinstance(v,list) and v and len(v)==len(set(v)) and all(x in spec[1:] for x in v)
    else:assert v in spec, 'Value outside fixed choices: '+str(v)
    if v=='other' or (isinstance(v,list) and 'other' in v):
        assert a['reason'].strip(), 'Other requires a reason'

def value(a):return a['value'] if a['status']=='observed' else None

def appearance(media_index,location):
    return {'media_index':media_index,'location':location,'attributes':{k:answer() for k in APPEARANCE_FIELDS}}

def template(post,provenance,worker_id='unassigned'):
    return {'schema_version':VERSION,'post_id':post['post_id'],'provenance':provenance,
      'execution':{'worker_id':worker_id,'started_at':datetime.now(timezone.utc).isoformat(),'finished_at':None,'model_version_if_available':None,'usage':None},
      'images':[{'media_index':i['media_index'],'sha256':i['sha256'],'viewed':False,'read_error':None,
                 'attributes':{k:answer() for k in IMAGE_FIELDS},'character_ids':[]} for i in post['images']],
      'post_attributes':{k:answer() for k in POST_FIELDS},'characters':[],
      **{k:answer() for k in COUNT_FIELDS},'character_coverage':'partial',
      'context':{'state':'pending','attributes':{k:answer() for k in CONTEXT_FIELDS},'searches':0,'pages':0,'elapsed_seconds':0,'stop_reason':'pending'},
      'review_flags':[]}

def _fields(attrs,fields):
    assert set(attrs)==set(fields), 'Required fields differ: '+str(set(attrs)^set(fields))
    for k,spec in fields.items():
        try:validate_answer(attrs[k],spec)
        except AssertionError as e:raise AssertionError(k+': '+str(e)) from e

def validate(record,post,provenance):
    assert __debug__, 'Validation requires Python without -O'
    required={'schema_version','post_id','provenance','execution','images','post_attributes','characters','character_coverage','context','review_flags',*COUNT_FIELDS}
    assert set(record)==required
    assert record['schema_version']==VERSION and record['post_id']==post['post_id'] and record['provenance']==provenance
    ex=record['execution']
    assert set(ex)=={'worker_id','started_at','finished_at','model_version_if_available','usage'}
    assert isinstance(ex['worker_id'],str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,90}',ex['worker_id']) and ex['worker_id']!='unassigned'
    start,end=(datetime.fromisoformat(ex[k].replace('Z','+00:00')) for k in ('started_at','finished_at'))
    assert start.tzinfo and end.tzinfo and end>=start
    assert ex['model_version_if_available'] is None or (isinstance(ex['model_version_if_available'],str) and 0<len(ex['model_version_if_available'])<=150)
    if ex['usage'] is not None:
        assert isinstance(ex['usage'],dict) and ex['usage'] and set(ex['usage'])<={'input_tokens','output_tokens','cached_input_tokens'}
        assert all(type(v) is int and v>=0 for v in ex['usage'].values())
    expected={(i['media_index'],i['sha256']) for i in post['images']}
    assert expected and len(expected)==len(post['images']) and len({i[0] for i in expected})==len(expected)
    assert len(record['images'])==len(expected) and {(i['media_index'],i['sha256']) for i in record['images']}==expected
    images={i['media_index']:i for i in record['images']}
    for im in images.values():
        assert set(im)=={'media_index','sha256','viewed','read_error','attributes','character_ids'}
        assert type(im['media_index']) is int and im['media_index']>0 and type(im['viewed']) is bool
        assert isinstance(im['character_ids'],list) and len(im['character_ids'])==len(set(im['character_ids']))
        _fields(im['attributes'],IMAGE_FIELDS)
        a=im['attributes']
        if not im['viewed']:
            assert isinstance(im['read_error'],str) and im['read_error'].strip() and len(im['read_error'])<=300
            assert not im['character_ids'] and all(v['status']=='technical_failure' for v in a.values())
            continue
        assert im['read_error'] is None
        assert a['content_kind']['status']!='not_applicable' and a['illustration_present']['status']!='not_applicable'
        present=value(a['illustration_present'])
        if value(a['content_kind'])=='illustration':assert present is True
        if present is False:
            assert not im['character_ids']
            assert all(v['status']=='not_applicable' for k,v in a.items() if k not in {'content_kind','illustration_present'}), 'Photo/UI is not illustration content'
        elif present is True:
            for k in ('main_subject','format','technique','coloring_state','color_presence','background','person_animal_presence','object_count','time_of_day',*('has_'+c+'_hair' for c in COLORS)):
                assert a[k]['status']!='not_applicable', k+' must be assessed for an illustration'
            if value(a['background']) in {'none','solid_color'}:
                assert a['environment']['status']=='not_applicable', 'No depicted environment: do not invent nature/city/interior'
            if value(a['object_count'])=='other' and a['object_count']['reason']=='no_objects':
                assert a['object_kind']['status']=='not_applicable'
            if value(a['object_count']) in {'single','multiple'}:
                assert a['object_kind']['status']!='not_applicable', 'Depicted objects require object kind assessment'
            if value(a['format'])=='design':
                assert a['design_kind']['status']!='not_applicable', 'A design requires its design kind'
        # Deliberately no branch on main_subject. Time is independent of environment.
    _fields(record['post_attributes'],POST_FIELDS)
    assert record['character_coverage'] in {'complete','partial'}
    chars=record['characters'];assert isinstance(chars,list)
    seen=set();observations={i:[] for i in images};known_counted=[];ambiguous_roles=False
    for char in chars:
        assert set(char)=={'id','grouping_evidence','observation_type','count_role','appearances'}
        cid=char['id'];assert isinstance(cid,str) and re.fullmatch(r'c[1-9][0-9]*',cid) and cid not in seen
        seen.add(cid)
        assert isinstance(char['grouping_evidence'],str) and 0<len(char['grouping_evidence'])<=600
        assert char['observation_type'] in {'individual','group'}
        role=char['count_role'];assert role in {'individual','background_extra','uncertain'}
        assert char['observation_type']!='group' or role!='individual', 'A crowd observation is not one person'
        ambiguous_roles|=role=='uncertain'
        apps=char['appearances'];assert isinstance(apps,list) and apps
        locations=set();media=set();kinds=set();kind_uncertain=False
        for app in apps:
            assert set(app)=={'media_index','location','attributes'}
            index=app['media_index'];assert index in images and images[index]['viewed']
            assert isinstance(app['location'],str) and 0<len(app['location'])<=300
            assert (index,app['location']) not in locations, 'Duplicate appearance location'
            locations.add((index,app['location']));media.add(index)
            _fields(app['attributes'],APPEARANCE_FIELDS)
            a=app['attributes'];kind=value(a['entity_kind']);shape=value(a['body_form'])
            assert a['entity_kind']['status']!='not_applicable' and a['body_form']['status']!='not_applicable'
            kinds.add(kind);kind_uncertain|=kind is None
            if role=='background_extra':assert kind=='person', 'The human mob rule must not discard animal herds'
            if kind=='person':
                for k in ('gender_presentation','crop','expression','age_presentation'):assert a[k]['status']!='not_applicable', k+' is required for depicted people'
                assert a['animal_kind']['status']==a['animal_style']['status']==a['animal_range']['status']=='not_applicable'
            elif kind=='animal':
                for k in ('animal_kind','animal_style','animal_range','expression'):assert a[k]['status']!='not_applicable', k+' is required for animals'
                assert a['crop']['status']=='not_applicable'
            elif kind=='other':
                assert a['animal_kind']['status']==a['animal_style']['status']=='not_applicable'
                if shape=='human_like':assert a['crop']['status']!='not_applicable'
                else:assert a['animal_range']['status']!='not_applicable'
            basis=value(a['hair_basis']);hair=a['hair_colors']
            assert a['hair_basis']['status']!='not_applicable'
            if basis=='uncolored':assert hair['status']=='unknown', 'Uncolored hair/paper must not become a hair color'
            if basis=='no_hair':assert hair['status']=='not_applicable'
            if hair['status']=='not_applicable':assert basis=='no_hair'
            if hair['status']=='observed':
                assert basis=='colored_or_toned', 'Observed hair needs actual hair color/tone evidence'
                for color in hair['value']:
                    flag=images[index]['attributes']['has_'+color+'_hair']
                    assert value(flag) is True, 'Visible hair must be present in the independent image observation'
            if a['gender_presentation']['status']=='observed' and value(a['gender_presentation'])=='multiple':
                assert char['observation_type']=='group', 'Do not combine distinct individual appearances into gender multiple'
            observations[index].append((char,a))
        assert media=={i for i,im in images.items() if cid in im['character_ids']}, 'Image/character links differ'
        if role=='individual':known_counted.append((cid,kinds,kind_uncertain))
    assert all(set(im['character_ids'])<=seen for im in images.values())
    all_viewed=all(im['viewed'] for im in images.values())
    complete=record['character_coverage']=='complete'
    if complete:assert all_viewed and not ambiguous_roles, 'Complete identities cannot include unresolved roles/unseen images'
    for field in COUNT_FIELDS:
        count=record[field];validate_answer(count,'integer')
        assert count['status']!='not_applicable'
        if count['status']=='observed':assert all_viewed and not ambiguous_roles, 'A confirmed count requires all images and resolved roles'
    total=record['character_count']
    if total['status']=='observed':
        assert complete and total['value']==len(known_counted), 'Count unique individual IDs, not appearances or crowd groups'
    if complete:assert total['status']=='observed'
    for field,kind in [('person_count','person'),('animal_count','animal')]:
        answer_count=record[field]
        ambiguous=any(uncertain or len(kinds)!=1 for _,kinds,uncertain in known_counted)
        if answer_count['status']=='observed':
            assert complete and not ambiguous, 'Entity kind uncertainty prevents an exact category count'
            assert answer_count['value']==sum(kinds=={kind} for _,kinds,_ in known_counted)
        elif complete and not ambiguous:
            raise AssertionError('Fully known identities require the exact '+field)
    for index,im in images.items():
        if not im['viewed']:continue
        attrs=im['attributes'];obs=observations[index]
        if any(value(a['entity_kind']) in {'person','animal'} for _,a in obs):
            assert value(attrs['person_animal_presence']) is True, 'Presence includes background extras independently of counts'
        if complete:
            for color in COLORS:
                if value(attrs['has_'+color+'_hair']) is True:
                    assert any(a['hair_colors']['status']=='observed' and color in a['hair_colors']['value'] for _,a in obs), 'Visible hair needs an individual/group observation, even for mobs'
        # Never derive absence or unknown flags from person_count or counted IDs.
    ctx=record['context']
    assert set(ctx)=={'state','attributes','searches','pages','elapsed_seconds','stop_reason'}
    _fields(ctx['attributes'],CONTEXT_FIELDS)
    has_illustration=any(value(im['attributes']['illustration_present']) is True for im in images.values())
    no_illustration=all(value(im['attributes']['illustration_present']) is False for im in images.values())
    if has_illustration:
        assert all(a['status']!='not_applicable' for a in [*record['post_attributes'].values(),*ctx['attributes'].values()]), 'Illustrated posts require work form, creation and promotion assessments'
    if no_illustration:
        assert all(a['status']=='not_applicable' for a in [*record['post_attributes'].values(),*ctx['attributes'].values()]), 'Non-illustrated posts have no illustration-level post attributes'
    failed=any(a['status']=='technical_failure' for a in ctx['attributes'].values())
    assert ctx['state']==('technical_failure' if failed else 'complete')
    creation=ctx['attributes']['creation']
    if creation['status']=='observed':assert creation['sources'], 'Creation attribution requires source evidence'
    assert type(ctx['searches']) is int and 0<=ctx['searches']<=2
    assert type(ctx['pages']) is int and 0<=ctx['pages']<=3
    assert type(ctx['elapsed_seconds']) in (int,float) and math.isfinite(ctx['elapsed_seconds']) and 0<=ctx['elapsed_seconds']<86400
    assert ctx['stop_reason'] in {'evidence_sufficient','no_leads','budget_exhausted','not_applicable','source_unavailable','tool_unavailable'}
    if failed:assert ctx['stop_reason'] in {'source_unavailable','tool_unavailable'}
    assert isinstance(record['review_flags'],list) and all(isinstance(x,str) and len(x)<=300 for x in record['review_flags'])
    return record

def definition():
    return {'version':VERSION,'image':IMAGE_FIELDS,'appearance':APPEARANCE_FIELDS,'post':POST_FIELDS,'context':CONTEXT_FIELDS,'counts':COUNT_FIELDS,'original_question_map':QUESTION_MAP,'optional_fields':[]}

if __name__=='__main__':
    import json
    print(json.dumps(definition(),ensure_ascii=False,indent=2))
