"""Frozen v2 pilot contract; validation never generates visual answers."""
from datetime import datetime, timezone
import re

VERSION = 'v2-pilot-1'
COLORS = 'black brown blond_yellow red orange pink purple blue green white gray other'.split()
IMAGE_FIELDS = {
    'content_kind': 'illustration photo screenshot mixed other'.split(),
    'format': 'illustration comic design mixed other'.split(),
    'subject_types': ['set', 'human_like', 'animal_like', 'hybrid', 'object', 'landscape', 'design', 'other'],
    'color_mode': 'multicolor monochrome grayscale limited_palette mixed'.split(),
    'background': 'plain_paper solid_color abstract_decorative environment mixed'.split(),
    'background_detail': 'none simple detailed'.split(),
    'technique': 'digital analog mixed other'.split(),
    'work_in_progress': 'boolean',
    'visible_promotion': 'boolean',
    'environment': ['set', 'nature', 'city', 'interior', 'fantasy', 'other'],
    'time_of_day': 'morning daytime evening night mixed'.split(),
    'design_kind': ['set', 'text', 'logo', 'poster', 'pattern', 'decoration', 'other'],
    'depiction_count': 'integer',
    **{'has_' + c + '_hair': 'boolean' for c in COLORS},
}
DEPICTION_FIELDS = {
    'body_form': 'human_like animal_like hybrid object_like other'.split(),
    'animal_features': 'boolean',
    'anthropomorphism': 'boolean',
    'style': 'realistic stylized mixed'.split(),
    'crop': 'face bust waist full_body other_partial'.split(),
    'expression': ['set', 'smile', 'neutral', 'anger', 'sadness', 'surprise', 'other'],
    'hair_colors': ['set', *COLORS],
    'fur_colors': ['set', *COLORS],
}
CONTEXT_FIELDS = {
    'creation': 'original derivative official mixed'.split(),
    'poster_relation': 'self_claimed repost_claimed other'.split(),
    'promotion': 'boolean',
}
STATES = {'observed', 'unknown', 'not_applicable', 'not_assessed', 'technical_failure'}


def answer(status='not_assessed', value=None, reason='pending', evidence=''):
    return dict(status=status, value=value, reason=reason, evidence=evidence, sources=[])


def template(post, provenance, worker_id='unassigned'):
    return {'schema_version': VERSION, 'post_id': post['post_id'], 'provenance': provenance,
            'execution': {'worker_id': worker_id, 'started_at': datetime.now(timezone.utc).isoformat(),
                          'finished_at': None, 'model_version_if_available': None, 'usage': None},
            'images': [dict(media_index=i['media_index'], sha256=i['sha256'], viewed=False,
                            read_error=None, detail_coverage='complete',
                            attributes={k: answer() for k in IMAGE_FIELDS}, depictions=[]) for i in post['images']],
            'context': {'state': 'pending', 'attributes': {k: answer() for k in CONTEXT_FIELDS},
                        'searches': 0, 'pages': 0, 'elapsed_seconds': 0, 'stop_reason': 'pending'},
            'review_flags': []}


def validate_answer(a, spec, allow_pending=False):
    assert isinstance(a, dict) and set(a) == {'status', 'value', 'reason', 'evidence', 'sources'}, 'Answer fields differ'
    assert a['status'] in STATES
    assert isinstance(a['reason'], str) and isinstance(a['evidence'], str)
    assert len(a['evidence']) <= 600 and len(a['reason']) <= 200
    assert isinstance(a['sources'], list) and len(a['sources']) <= 5
    for s in a['sources']:
        assert isinstance(s, dict) and set(s) == {'url', 'accessed_at', 'kind'}
        assert isinstance(s['url'], str) and s['url'].startswith('https://')
        assert s['kind'] in ('post_text', 'external_source')
        datetime.fromisoformat(s['accessed_at'].replace('Z', '+00:00'))
    if a['status'] != 'observed':
        assert a['value'] is None and a['reason'].strip(), 'Missing/unknown values need reason and null'
        assert allow_pending or a['status'] != 'not_assessed', 'Required field remains unassessed'
        return
    assert a['evidence'].strip(), 'Observed answer requires short evidence'
    v = a['value']
    if spec == 'boolean':
        assert type(v) is bool
    elif spec == 'integer':
        assert type(v) is int and 0 <= v <= 100000
    elif spec[0] == 'set':
        assert isinstance(v, list) and v and all(x in spec[1:] for x in v) and len(v) == len(set(v))
    else:
        assert v in spec


def validate(record, post, provenance):
    assert set(record) == {'schema_version', 'post_id', 'provenance', 'execution', 'images', 'context', 'review_flags'}
    execution = record['execution']
    assert set(execution) == {'worker_id', 'started_at', 'finished_at', 'model_version_if_available', 'usage'}
    assert isinstance(execution['worker_id'], str) and execution['worker_id'] != 'unassigned'
    assert isinstance(execution['started_at'], str) and isinstance(execution['finished_at'], str)
    start = datetime.fromisoformat(execution['started_at'].replace('Z', '+00:00'))
    end = datetime.fromisoformat(execution['finished_at'].replace('Z', '+00:00'))
    assert start.tzinfo is not None and end.tzinfo is not None and end >= start
    assert record['schema_version'] == VERSION and record['post_id'] == post['post_id']
    assert record['provenance'] == provenance, 'Provenance was changed or belongs to another run'
    expected = {(i['media_index'], i['sha256']) for i in post['images']}
    images = record['images']
    assert isinstance(images, list) and len(images) == len(expected)
    assert {(i['media_index'], i['sha256']) for i in images} == expected, 'All image positions/hashes must match'
    for i in images:
        assert set(i) == {'media_index', 'sha256', 'viewed', 'read_error', 'detail_coverage', 'attributes', 'depictions'}
        assert type(i['viewed']) is bool and i['detail_coverage'] in ('complete', 'partial')
        assert set(i['attributes']) == set(IMAGE_FIELDS)
        if not i['viewed']:
            assert isinstance(i['read_error'], str) and i['read_error'].strip()
            assert all(a['status'] == 'technical_failure' for a in i['attributes'].values())
            assert not i['depictions']
        else:
            assert i['read_error'] is None
        for k, a in i['attributes'].items():
            validate_answer(a, IMAGE_FIELDS[k])
            if k.startswith('has_'):
                assert a['status'] != 'not_applicable', 'Presence flag must be true/false/unknown/failure'
        assert isinstance(i['depictions'], list) and len(i['depictions']) <= 12
        ids = set()
        for d in i['depictions']:
            assert set(d) == {'id', 'location', 'attributes', 'identity'}
            assert re.fullmatch(r'd[1-9][0-9]*', d['id']) and d['id'] not in ids
            ids.add(d['id'])
            assert isinstance(d['location'], str) and d['location'].strip()
            assert set(d['attributes']) == set(DEPICTION_FIELDS)
            for k, a in d['attributes'].items():
                validate_answer(a, DEPICTION_FIELDS[k])
            ident = d['identity']
            assert set(ident) == {'status', 'name', 'work', 'evidence', 'sources'}
            assert ident['status'] in ('identified', 'original_claimed', 'unresolved', 'not_applicable')
            assert all(isinstance(ident[k], str) for k in ('name', 'work', 'evidence'))
            if ident['status'] in ('identified', 'original_claimed'):
                assert ident['evidence'].strip()
            hair = d['attributes']['hair_colors']
            if hair['status'] == 'observed':
                for color in hair['value']:
                    presence = i['attributes']['has_' + color + '_hair']
                    assert presence['status'] == 'observed' and presence['value'] is True, 'Hair presence contradicts depiction'
        count = i['attributes']['depiction_count']
        if count['status'] == 'observed':
            assert count['value'] >= len(ids)
            if i['detail_coverage'] == 'complete':
                assert count['value'] == len(ids), 'Complete coverage must enumerate each depiction'
    c = record['context']
    assert set(c) == {'state', 'attributes', 'searches', 'pages', 'elapsed_seconds', 'stop_reason'}
    assert c['state'] in ('pending', 'complete', 'technical_failure')
    assert type(c['searches']) is int and 0 <= c['searches'] <= 2
    assert type(c['pages']) is int and 0 <= c['pages'] <= 3
    assert type(c['elapsed_seconds']) in (int, float) and 0 <= c['elapsed_seconds'] < 86400
    assert isinstance(c['stop_reason'], str) and c['stop_reason'].strip()
    assert set(c['attributes']) == set(CONTEXT_FIELDS)
    for k, a in c['attributes'].items():
        validate_answer(a, CONTEXT_FIELDS[k], allow_pending=c['state'] == 'pending')
        if k == 'creation' and a['status'] == 'observed':
            assert a['sources'], 'Creation labels require directly attributable evidence'
    assert isinstance(record['review_flags'], list) and all(isinstance(x, str) for x in record['review_flags'])
    return record
