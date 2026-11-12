"""Small authoring helpers: expand explicit observations, never infer research labels."""
from . import contract_v4 as c

def observed(value,evidence,reason='',sources=None):
    return c.answer('observed',value,reason,evidence,sources)
def unknown(reason):return c.answer('unknown',reason=reason)
def na(reason):return c.answer('not_applicable',reason=reason)
def failed(reason):return c.answer('technical_failure',reason=reason)

def new_character(cid,grouping_evidence,role='individual',observation_type='individual'):
    return dict(id=cid,grouping_evidence=grouping_evidence,count_role=role,observation_type=observation_type,appearances=[])

def new_appearance(media_index,location,**attributes):
    app=c.appearance(media_index,location)
    assert set(attributes)<=set(c.APPEARANCE_FIELDS)
    app['attributes'].update(attributes)
    a=app['attributes'];kind=c.value(a['entity_kind']);shape=c.value(a['body_form'])
    irrelevant=[]
    if kind=='person':irrelevant=['animal_kind','animal_style','animal_range']
    elif kind=='animal':irrelevant=['crop','gender_presentation','age_presentation']
    elif kind=='other':irrelevant=['animal_kind','animal_style', 'animal_range' if shape=='human_like' else 'crop']
    for key in irrelevant:
        if a[key]['status']=='not_assessed':a[key]=na('not_a_target_for_this_entity_feature')
    basis=c.value(a['hair_basis'])
    if a['hair_colors']['status']=='not_assessed':
        if basis=='uncolored':a['hair_colors']=unknown('uncolored_hair; do not use paper or blank areas as hair color')
        elif basis=='no_hair':a['hair_colors']=na('no_hair')
    return app

def link_characters(record):
    """Only link supplied observations. This does not infer image presence or hair flags."""
    for im in record['images']:
        im['character_ids']=[ch['id'] for ch in record['characters'] if any(a['media_index']==im['media_index'] for a in ch['appearances'])]

def record_complete_counts(record,evidence):
    """Call only after explicitly confirming complete unique identities across all images."""
    assert all(im['viewed'] for im in record['images'])
    assert all(ch['count_role']!='uncertain' for ch in record['characters'])
    chars=[ch for ch in record['characters'] if ch['count_role']=='individual']
    assert all(ch['observation_type']=='individual' for ch in chars)
    kinds=[{c.value(a['attributes']['entity_kind']) for a in ch['appearances']} for ch in chars]
    record['character_coverage']='complete'
    record['character_count']=observed(len(chars),evidence)
    for field,kind in [('person_count','person'),('animal_count','animal')]:
        record[field]=(unknown('entity_kind_or_change_unresolved') if any(None in ks or len(ks)!=1 for ks in kinds)
                       else observed(sum(ks=={kind} for ks in kinds),evidence))
    link_characters(record)

def no_illustration(im,media_kind,evidence):
    """Explicit visual conclusion: no drawing inside the photo/screenshot."""
    assert im['viewed'] is True
    im['attributes']={k:na('no_illustrated_region') for k in c.IMAGE_FIELDS}
    im['attributes'].update(content_kind=observed(media_kind,evidence),illustration_present=observed(False,evidence))
    im['character_ids']=[]
