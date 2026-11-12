"""Collect completed batches only. Preserve incomplete/unknown/failure counts explicitly."""
import argparse
from collections import Counter
import csv
import hashlib
import io
import json
from pathlib import Path

from .common import atomic_write, canonical
from .contract import COLORS
from .git_queue import GitQueue
from .worker import check_config, provenance, schema_for, validate_result
from .disposition import is_exclusion


def aggregate_hair(images, color):
    values = [i['attributes']['has_' + color + '_hair'] for i in images]
    if any(v['status'] == 'observed' and v['value'] is True for v in values):
        return 'true'
    if all(v['status'] == 'observed' and v['value'] is False for v in values):
        return 'false'
    return 'unknown'


def aggregate_person_or_animal(record):
    """Presence is independent of the main subject; partial absence is unknown."""
    forms = [c['attributes']['body_form'] for c in record['characters']]
    if any(a['status'] == 'observed' and a['value'] in {'human_like', 'animal_like'} for a in forms):
        return 'true'
    if (record['character_coverage'] == 'complete'
            and all(im['viewed'] for im in record['images'])
            and all(a['status'] == 'observed' and a['value'] == 'other' for a in forms)):
        return 'false'
    return 'unknown'


def write_table(path, columns, rows):
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream,fieldnames=columns)
    writer.writeheader()
    writer.writerows(rows)
    atomic_write(path,('\ufeff'+stream.getvalue()).encode('utf-8'))


def answer_columns(attributes, fields):
    out = {}
    for field in fields:
        a = attributes.get(field)
        # Empty means an omitted optional attribute, never a negative observation.
        out[field] = (json.dumps(a['value'],ensure_ascii=False) if isinstance(a['value'],list) else a['value']) if a else None
        out[field+'_status'] = a['status'] if a else 'not_assessed'
    return out


def export_v3(output, ordered, schema):
    images, characters, appearances = [], [], []
    profile = {}
    for r in ordered:
        for im in r['images']:
            images.append({'post_id':r['post_id'],'media_index':im['media_index'],'viewed':im['viewed'],
                           **answer_columns(im['attributes'],schema.IMAGE_FIELDS)})
            for field,a in im['attributes'].items():
                profile.setdefault('image.'+field,Counter())[a['status']+(':'+str(a['value']).lower() if a['status']=='observed' else '')] += 1
        for char in r['characters']:
            fields = list(schema.CHARACTER_FIELDS)+list(schema.OPTIONAL_CHARACTER_FIELDS)
            characters.append({'post_id':r['post_id'],'character_id':char['id'],**answer_columns(char['attributes'],fields)})
            for app in char['appearances']:
                appearances.append({'post_id':r['post_id'],'character_id':char['id'],'media_index':app['media_index'],
                                    **answer_columns({'hair_colors':app['hair_colors']},['hair_colors'])})
        a = r['context']['attributes']['creation']
        profile.setdefault('post.creation',Counter())[a['status']+(':'+a['value'] if a['status']=='observed' else '')] += 1
        profile.setdefault('post.character_coverage',Counter())[r['character_coverage']] += 1
    imagecols = [c for f in schema.IMAGE_FIELDS for c in (f,f+'_status')]
    charcols = [c for f in list(schema.CHARACTER_FIELDS)+list(schema.OPTIONAL_CHARACTER_FIELDS) for c in (f,f+'_status')]
    write_table(output/'images.csv',['post_id','media_index','viewed',*imagecols],images)
    write_table(output/'characters.csv',['post_id','character_id',*charcols],characters)
    write_table(output/'appearances.csv',['post_id','character_id','media_index','hair_colors','hair_colors_status'],appearances)
    atomic_write(output/'quality-profile.json',canonical({'units':{'posts':len(ordered),'images':len(images),'unique_characters_within_posts':len(characters),'character_image_appearances':len(appearances)},
                 'status_and_value_counts':profile,'note':'Distributions and missingness only, not measured labeling accuracy. Character IDs are scoped to one post.'}))


def collect(config_path, output, remote=None):
    config, catalog = check_config(config_path)
    jobs = {j['job_id']: j for j in catalog['jobs'] if j['job_id'] in config['job_ids']}
    rows, receipts, counts = {}, {}, Counter()
    with GitQueue(remote or config['remote'], config['run_id'], config['catalog_sha256']) as q:
        heads = q.heads()
        for jid, job in jobs.items():
            if jid not in heads:
                counts['unclaimed_jobs'] += 1
                continue
            sha, state = q.read(jid)
            if state['status'] != 'completed':
                counts[state['status'] + '_jobs'] += 1
                continue
            raw = q.git('show', sha + ':labels.jsonl').stdout
            assert hashlib.sha256(raw).hexdigest() == state['result_sha256']
            manifest_bytes = q.git('show', sha + ':manifest.json').stdout
            assert hashlib.sha256(manifest_bytes).hexdigest() == job['manifest_sha256']
            manifest = json.loads(manifest_bytes)
            expected_posts = {p['post_id']: p for p in manifest['posts']}
            batch = [json.loads(line) for line in raw.splitlines()]
            assert len(batch) == len(job['post_ids']) == state['result_count']
            assert {r['post_id'] for r in batch} == set(job['post_ids'])
            for row in batch:
                validate_result(row,expected_posts[row['post_id']],config,manifest)
                prov = row['provenance']
                for k in ('run_id', 'catalog_sha256', 'manual_sha256', 'contract_sha256', 'schema_version', 'model_id', 'reasoning_effort'):
                    assert prov[k] == config[k], 'Result provenance mismatch'
                pid = row['post_id']
                assert pid not in rows, 'Duplicate post result across batches'
                rows[pid] = row
            receipts[jid] = {'head': sha, 'result_sha256': state['result_sha256']}
            counts['completed_jobs' if config['schema_version']=='v3-1' else 'completed_visual_jobs'] += 1
    output = Path(output)
    excluded = [rows[k] for k in sorted(rows) if is_exclusion(rows[k])]
    ordered = [rows[k] for k in sorted(rows) if not is_exclusion(rows[k])]
    atomic_write(output / 'labels.jsonl', b''.join(canonical(r) for r in ordered))
    table = io.StringIO(newline='')
    modern = config['schema_version'] == 'v3-1'
    columns = ['post_id', 'image_count', 'visual_technical_failure', 'context_state', 'creation', *(['creation_status','character_count','character_count_status','character_coverage','has_person_or_animal'] if modern else []), *['has_' + c + '_hair' for c in COLORS]]
    writer = csv.DictWriter(table, fieldnames=columns)
    writer.writeheader()
    reviews = []
    for r in ordered:
        failure = any(not i['viewed'] for i in r['images'])
        counts['posts_with_visual_failure'] += int(failure)
        counts['context_' + r['context']['state']] += 1
        creation = r['context']['attributes']['creation']
        writer.writerow({'post_id': r['post_id'], 'image_count': len(r['images']), 'visual_technical_failure': failure,
                         'context_state': r['context']['state'], 'creation': creation['value'] or creation['status'],
                         **({'creation_status':creation['status'],'character_count': r['character_count']['value'], 'character_count_status': r['character_count']['status'],'character_coverage':r['character_coverage'], 'has_person_or_animal':aggregate_person_or_animal(r)} if modern else {}),
                         **{'has_' + c + '_hair': aggregate_hair(r['images'], c) for c in COLORS}})
        # Deterministic 2% random audit, separately flagged from targeted failure reviews.
        audit = int(hashlib.sha256((config['run_id'] + r['post_id']).encode()).hexdigest()[:8], 16) % 50 == 0
        if failure or r['review_flags'] or audit:
            reviews.append({'post_id': r['post_id'], 'random_audit': audit, 'visual_failure': failure, 'flags': r['review_flags']})
    atomic_write(output / 'posts.csv', ('\ufeff' + table.getvalue()).encode('utf-8'))
    atomic_write(output / 'review_queue.jsonl', b''.join(canonical(r) for r in reviews))
    if modern:
        export_v3(output,ordered,schema_for(config))
        atomic_write(output/'exclusions.jsonl',b''.join(canonical(r) for r in excluded))
        cols=['post_id','reason','signal','temporary','scope','blocked_media_index','excluded_at']
        write_table(output/'exclusions.csv',cols,[{k:r[k] for k in cols} for r in excluded])
        counts['policy_excluded_posts']=len(excluded)
    summary = {'run_id': config['run_id'], 'processed_posts': len(ordered), 'expected_posts': sum(len(j['post_ids']) for j in jobs.values()),
               **({'resolved_posts':len(rows),'excluded_posts':len(excluded)} if modern else {}),
               'counts': dict(counts), 'jobs': receipts, 'note': 'Visual job completion does not imply context completion or correctness.'}
    atomic_write(output / 'receipt.json', canonical(summary))
    print(json.dumps({k: v for k, v in summary.items() if k != 'jobs'}))


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--config', default='runs/pilot-v2-001.json')
    p.add_argument('--output', default='.runtime/collected')
    p.add_argument('--remote')
    a = p.parse_args()
    collect(a.config, a.output, a.remote)
