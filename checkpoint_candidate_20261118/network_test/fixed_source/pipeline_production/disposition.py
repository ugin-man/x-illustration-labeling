"""Minimal processing exclusions, deliberately separate from research labels."""
from datetime import datetime, timezone

VERSION = 'policy-exclusion-1'
SIGNALS = {'model_refusal', 'image_tool_refusal'}


def is_exclusion(record):
    return record.get('record_type') == 'exclusion'


def create(post, provenance, worker_id, signal, media_index=None):
    row = {'record_type':'exclusion','disposition_version':VERSION,
           'schema_version':provenance['schema_version'],'post_id':post['post_id'],
           'provenance':provenance, 'worker_id':worker_id,
           'excluded_at':datetime.now(timezone.utc).isoformat(),
           'reason':'policy_refusal', 'signal':signal, 'temporary':True,
           'scope':'post', 'blocked_media_index':media_index}
    validate(row,post,provenance)
    return row


def validate(row, post, provenance):
    if not __debug__:
        raise ValueError('Validation requires Python without -O')
    assert set(row)=={'record_type','disposition_version','schema_version','post_id','provenance','worker_id',
                      'excluded_at','reason','signal','temporary','scope','blocked_media_index'}, 'Exclusion must contain metadata only'
    assert row['record_type']=='exclusion' and row['disposition_version']==VERSION
    assert row['schema_version']==provenance['schema_version']=='v4-1'
    assert row['post_id']==post['post_id'] and row['provenance']==provenance
    assert isinstance(row['worker_id'],str) and row['worker_id'].strip() and len(row['worker_id'])<=91
    assert row['reason']=='policy_refusal' and row['signal'] in SIGNALS
    assert row['temporary'] is True and row['scope']=='post'
    index=row['blocked_media_index']
    assert index is None or (type(index) is int and index in {i['media_index'] for i in post['images']})
    assert datetime.fromisoformat(row['excluded_at'].replace('Z','+00:00')).tzinfo
    return row
