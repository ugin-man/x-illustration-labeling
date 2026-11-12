"""Fixed, compact v3 labels. One character per post; never one character per panel."""
from datetime import datetime, timezone
import math
import re
from urllib.parse import urlsplit

VERSION = 'v3-1'
COLORS = 'black brown blond_yellow red orange pink purple blue green white gray other'.split()
IMAGE_FIELDS = {
    'main_subject': 'person_or_animal object landscape design other'.split(),
    'content_kind': 'illustration photo screenshot other'.split(),
    'format': 'illustration comic design other'.split(),
    'technique': 'digital analog'.split(),
    'color_presence': 'chromatic achromatic'.split(),
    'background': 'none solid_color simple detailed other'.split(),
    **{'has_' + c + '_hair': 'boolean' for c in COLORS},
}
CHARACTER_FIELDS = {'body_form': 'human_like animal_like other'.split()}
OPTIONAL_CHARACTER_FIELDS = {
    'crop': ['set', 'face', 'bust', 'waist_up', 'full_body', 'other_partial'],
    'expression': ['set', 'smile', 'neutral', 'anger', 'sadness', 'surprise', 'other'],
}
CONTEXT_FIELDS = {'creation': 'original derivative other'.split()}
STATES = {'observed','unknown','not_applicable','not_assessed','technical_failure'}


def answer(status='not_assessed', value=None, reason='pending', evidence=''):
    return dict(status=status, value=value, reason=reason, evidence=evidence, sources=[])


def validate_answer(a, spec, allow_pending=False):
    assert isinstance(a, dict) and set(a) == {'status','value','reason','evidence','sources'}
    assert a['status'] in STATES
    assert isinstance(a['reason'], str) and len(a['reason']) <= 200
    assert isinstance(a['evidence'], str) and len(a['evidence']) <= 600
    assert isinstance(a['sources'], list) and len(a['sources']) <= 5
    for s in a['sources']:
        assert set(s) == {'url','accessed_at','kind'} and s['kind'] in {'post_text','external_source'}
        assert isinstance(s['url'], str) and len(s['url']) <= 2000
        url = urlsplit(s['url'])
        assert url.scheme == 'https' and url.hostname and not url.username and not url.password
        assert datetime.fromisoformat(s['accessed_at'].replace('Z','+00:00')).tzinfo
    if a['status'] != 'observed':
        assert a['value'] is None and a['reason'].strip()
        assert allow_pending or a['status'] != 'not_assessed'
        return
    assert a['evidence'].strip()
    v = a['value']
    if spec == 'boolean':
        assert type(v) is bool
    elif spec == 'integer':
        assert type(v) is int and 0 <= v <= 100000
    elif spec[0] == 'set':
        assert isinstance(v, list) and v and all(x in spec[1:] for x in v) and len(v) == len(set(v))
    else:
        assert v in spec


def template(post, provenance, worker_id='unassigned'):
    return {'schema_version': VERSION, 'post_id': post['post_id'], 'provenance': provenance,
            'execution': {'worker_id':worker_id, 'started_at':datetime.now(timezone.utc).isoformat(),
                          'finished_at':None, 'model_version_if_available':None, 'usage':None},
            'images':[{'media_index':i['media_index'],'sha256':i['sha256'],'viewed':False,'read_error':None,
                       'attributes':{k:answer() for k in IMAGE_FIELDS}, 'character_ids':[]} for i in post['images']],
            'characters':[], 'character_count':answer(), 'character_coverage':'partial',
            'context':{'state':'pending','attributes':{'creation':answer()},'searches':0,'pages':0,'elapsed_seconds':0,'stop_reason':'pending'},
            'review_flags':[]}


def validate(record, post, provenance):
    if not __debug__:
        raise ValueError('Validation requires Python without -O')
    assert set(record) == {'schema_version','post_id','provenance','execution','images','characters','character_count','character_coverage','context','review_flags'}
    assert record['schema_version'] == VERSION and record['post_id'] == post['post_id'] and record['provenance'] == provenance
    ex = record['execution']
    assert set(ex) == {'worker_id','started_at','finished_at','model_version_if_available','usage'}
    assert isinstance(ex['worker_id'],str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,90}',ex['worker_id']) and ex['worker_id'] != 'unassigned'
    start,end = (datetime.fromisoformat(ex[k].replace('Z','+00:00')) for k in ['started_at','finished_at'])
    assert start.tzinfo and end.tzinfo and end >= start
    assert ex['model_version_if_available'] is None or (isinstance(ex['model_version_if_available'],str) and 0<len(ex['model_version_if_available'])<=150)
    if ex['usage'] is not None:
        assert isinstance(ex['usage'],dict) and set(ex['usage']) <= {'input_tokens','output_tokens','cached_input_tokens'}
        assert ex['usage'] and all(type(v) is int and v>=0 for v in ex['usage'].values())
    expected = {(i['media_index'],i['sha256']) for i in post['images']}
    assert expected and len(expected) == len(post['images']), 'Input contains missing or duplicate images'
    assert len({i['media_index'] for i in post['images']})==len(post['images']), 'Duplicate media index'
    assert all(type(i['media_index']) is int and i['media_index'] > 0 for i in record['images'])
    assert len(record['images']) == len(expected)
    assert {(i['media_index'],i['sha256']) for i in record['images']} == expected
    images = {i['media_index']: i for i in record['images']}
    for im in images.values():
        assert set(im) == {'media_index','sha256','viewed','read_error','attributes','character_ids'}
        assert type(im['viewed']) is bool and set(im['attributes']) == set(IMAGE_FIELDS)
        assert isinstance(im['character_ids'],list) and len(set(im['character_ids'])) == len(im['character_ids'])
        if not im['viewed']:
            assert isinstance(im['read_error'],str) and im['read_error'].strip() and len(im['read_error'])<=200
            assert not im['character_ids'] and all(a['status']=='technical_failure' for a in im['attributes'].values())
        else:
            assert im['read_error'] is None
        for k,a in im['attributes'].items():
            validate_answer(a, IMAGE_FIELDS[k])
            if k.startswith('has_'):
                assert a['status'] != 'not_applicable'
        assert im['attributes']['content_kind']['status'] != 'not_applicable', 'Every image has a content kind'
        kind = im['attributes']['content_kind']
        if kind['status'] == 'observed' and kind['value'] == 'illustration':
            assert im['attributes']['main_subject']['status'] != 'not_applicable', 'An illustration requires a main subject assessment'
    assert record['character_coverage'] in {'complete','partial'}
    chars = record['characters']
    assert isinstance(chars,list) and len(chars) <= 12
    seen = set()
    for char in chars:
        assert set(char) == {'id','grouping_evidence','attributes','appearances'}
        cid = char['id']
        assert re.fullmatch(r'c[1-9][0-9]*',cid) and cid not in seen
        seen.add(cid)
        assert isinstance(char['grouping_evidence'],str) and char['grouping_evidence'].strip() and len(char['grouping_evidence']) <= 600
        attrs = char['attributes']
        assert set(CHARACTER_FIELDS) <= set(attrs) <= set(CHARACTER_FIELDS) | set(OPTIONAL_CHARACTER_FIELDS)
        for k,a in attrs.items():
            validate_answer(a, (CHARACTER_FIELDS | OPTIONAL_CHARACTER_FIELDS)[k])
        assert attrs['body_form']['status'] != 'not_applicable', 'Every listed character has a body form'
        appearances = char['appearances']
        assert isinstance(appearances,list) and appearances and len(appearances) <= len(images)
        media = set()
        for app in appearances:
            assert set(app) == {'media_index','location','hair_colors'}
            index = app['media_index']
            assert index in images and index not in media and images[index]['viewed']
            media.add(index)
            assert isinstance(app['location'],str) and 0 < len(app['location']) <= 300
            validate_answer(app['hair_colors'], ['set',*COLORS])
            if app['hair_colors']['status'] == 'observed':
                for color in app['hair_colors']['value']:
                    presence = images[index]['attributes']['has_'+color+'_hair']
                    assert presence['status']=='observed' and presence['value'] is True, 'Hair/character inconsistency'
        assert media == {i for i, im in images.items() if cid in im['character_ids']}, 'Character/image links differ'
    assert all(set(im['character_ids']) <= seen for im in images.values()), 'Unknown character link'
    count = record['character_count']
    validate_answer(count,'integer')
    assert count['status'] != 'not_applicable'
    if count['status'] == 'observed':
        assert all(im['viewed'] for im in images.values()), 'Unseen images cannot yield a full post count'
        assert count['value'] >= len(chars)
        if record['character_coverage']=='complete':
            assert count['value']==len(chars), 'Count unique characters, not appearances'
    if record['character_coverage']=='complete':
        assert count['status']=='observed'
        for index, im in images.items():
            hair = [a['hair_colors'] for ch in chars for a in ch['appearances'] if a['media_index']==index]
            known = {color for a in hair if a['status']=='observed' for color in a['value']}
            all_known = all(a['status'] in {'observed','not_applicable'} for a in hair)
            for color in COLORS:
                flag = im['attributes']['has_'+color+'_hair']
                if all_known:
                    assert flag['status']=='observed' and flag['value']==(color in known), 'Complete character list contradicts image hair flags'
    context = record['context']
    assert set(context)=={'state','attributes','searches','pages','elapsed_seconds','stop_reason'}
    assert context['state'] in {'complete','technical_failure'}, 'Context must be assessed or explicitly unavailable before submission'
    assert set(context['attributes'])==set(CONTEXT_FIELDS)
    validate_answer(context['attributes']['creation'],CONTEXT_FIELDS['creation'])
    creation = context['attributes']['creation']
    assert (context['state']=='technical_failure') == (creation['status']=='technical_failure'), 'Context state and creation status differ'
    if context['attributes']['creation']['status']=='observed':
        assert context['attributes']['creation']['sources']
    assert type(context['searches']) is int and 0<=context['searches']<=2
    assert type(context['pages']) is int and 0<=context['pages']<=3
    assert type(context['elapsed_seconds']) in (int,float) and math.isfinite(context['elapsed_seconds']) and 0<=context['elapsed_seconds']<86400
    assert context['stop_reason'] in {'evidence_sufficient','no_leads','budget_exhausted','not_applicable','source_unavailable','tool_unavailable'}, 'Use a fixed context stop reason'
    if context['state']=='technical_failure':
        assert context['stop_reason'] in {'source_unavailable','tool_unavailable'}
    else:
        assert context['stop_reason'] not in {'source_unavailable','tool_unavailable'}
    if creation['status']=='observed':
        assert context['stop_reason']=='evidence_sufficient'
    if creation['status']=='not_applicable':
        assert context['stop_reason']=='not_applicable'
    if creation['status']=='unknown':
        assert context['stop_reason'] in {'no_leads','budget_exhausted'}
    assert isinstance(record['review_flags'],list) and len(record['review_flags'])<=20 and all(isinstance(x,str) and len(x)<=200 for x in record['review_flags'])
    return record


if __name__ == '__main__':
    import json
    print(json.dumps({'version':VERSION,'image':IMAGE_FIELDS,'character':CHARACTER_FIELDS,'optional_character':OPTIONAL_CHARACTER_FIELDS,'context':CONTEXT_FIELDS},ensure_ascii=False,indent=2))
