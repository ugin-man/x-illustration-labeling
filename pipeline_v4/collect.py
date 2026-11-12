"""Validate every completed v4 row, export every answer and its state, never modify jobs."""
import argparse
from collections import Counter
import csv
import hashlib
import io
import json
from pathlib import Path
from .common import atomic_write,canonical
from .contract_v4 import COLORS,IMAGE_FIELDS,APPEARANCE_FIELDS,POST_FIELDS,CONTEXT_FIELDS,COUNT_FIELDS,QUESTION_MAP
from .git_queue import GitQueue
from .worker import check_config,validate_result
from .disposition import is_exclusion

def aggregate(images,field):
    values=[i['attributes'][field] for i in images]
    if any(a['status']=='observed' and a['value'] is True for a in values):return 'true'
    if all((a['status']=='observed' and a['value'] is False) or a['status']=='not_applicable' for a in values):return 'false'
    return 'unknown'

def columns(attrs):
    out={}
    for k,a in attrs.items():
        out[k]=json.dumps(a['value'],ensure_ascii=False) if isinstance(a['value'],list) else a['value']
        out[k+'_status']=a['status'];out[k+'_reason']=a['reason']
    return out

def write_table(path,rows,fields):
    stream=io.StringIO(newline='');writer=csv.DictWriter(stream,fieldnames=fields)
    writer.writeheader();writer.writerows(rows)
    atomic_write(path,('\ufeff'+stream.getvalue()).encode('utf-8'))

def expanded(fields):return [k+s for k in fields for s in ('','_status','_reason')]

def export(output,ordered):
    output=Path(output);posts=[];images=[];characters=[];apps=[];answers=[];profile={}
    def add(pid,unit,unit_id,attrs):
        for k,a in attrs.items():
            answers.append(dict(post_id=pid,unit=unit,unit_id=unit_id,field=k,status=a['status'],value=json.dumps(a['value'],ensure_ascii=False),reason=a['reason'],evidence=a['evidence'],sources=json.dumps(a['sources'],ensure_ascii=False)))
            profile.setdefault(unit+'.'+k,Counter())[a['status']+(':'+json.dumps(a['value'],ensure_ascii=False) if a['status']=='observed' else '')]+=1
    for r in ordered:
        pid=r['post_id'];attrs={**r['post_attributes'],**{k:r[k] for k in COUNT_FIELDS},**r['context']['attributes']}
        posts.append(dict(post_id=pid,image_count=len(r['images']),character_coverage=r['character_coverage'],context_state=r['context']['state'],
                          **columns(attrs),has_person_or_animal=aggregate(r['images'],'person_animal_presence'),
                          **{'has_'+c+'_hair':aggregate(r['images'],'has_'+c+'_hair') for c in COLORS}))
        add(pid,'post',pid,attrs)
        for im in r['images']:
            images.append(dict(post_id=pid,media_index=im['media_index'],sha256=im['sha256'],viewed=im['viewed'],**columns(im['attributes'])))
            add(pid,'image',str(im['media_index']),im['attributes'])
        for ch in r['characters']:
            characters.append(dict(post_id=pid,character_id=ch['id'],count_role=ch['count_role'],observation_type=ch['observation_type'],grouping_evidence=ch['grouping_evidence']))
            for n,app in enumerate(ch['appearances'],1):
                apps.append(dict(post_id=pid,character_id=ch['id'],appearance_number=n,media_index=app['media_index'],location=app['location'],count_role=ch['count_role'],**columns(app['attributes'])))
                add(pid,'appearance',ch['id']+'.'+str(n),app['attributes'])
    write_table(output/'posts.csv',posts,['post_id','image_count','character_coverage','context_state',*expanded([*POST_FIELDS,*COUNT_FIELDS,*CONTEXT_FIELDS]),'has_person_or_animal',*('has_'+c+'_hair' for c in COLORS)])
    write_table(output/'images.csv',images,['post_id','media_index','sha256','viewed',*expanded(IMAGE_FIELDS)])
    write_table(output/'characters.csv',characters,['post_id','character_id','count_role','observation_type','grouping_evidence'])
    write_table(output/'appearances.csv',apps,['post_id','character_id','appearance_number','media_index','location','count_role',*expanded(APPEARANCE_FIELDS)])
    write_table(output/'answers.csv',answers,['post_id','unit','unit_id','field','status','value','reason','evidence','sources'])
    atomic_write(output/'quality-profile.json',canonical({'units':{'posts':len(ordered),'images':len(images),'character_records_including_mob_groups':len(characters),'appearance_records':len(apps)},'status_and_value_counts':profile,'original_question_map':QUESTION_MAP,'note':'Completeness/distributions only, not measured accuracy. Mob observation groups are not people counts.'}))

def collect(config_path,output,remote=None):
    config,catalog=check_config(config_path);jobs={j['job_id']:j for j in catalog['jobs'] if j['job_id'] in config['job_ids']}
    rows={};receipts={};counts=Counter()
    with GitQueue(remote or config['remote'],config['run_id'],config['catalog_sha256']) as q:
        heads=q.heads()
        for jid,job in jobs.items():
            if jid not in heads:counts['unclaimed_jobs']+=1;continue
            sha,state=q.read(jid)
            if state['status']!='completed':counts[state['status']+'_jobs']+=1;continue
            raw=q.git('show',sha+':labels.jsonl').stdout;mbytes=q.git('show',sha+':manifest.json').stdout
            assert hashlib.sha256(raw).hexdigest()==state['result_sha256'] and hashlib.sha256(mbytes).hexdigest()==job['manifest_sha256']
            manifest=json.loads(mbytes);posts={p['post_id']:p for p in manifest['posts']};batch=[json.loads(x) for x in raw.splitlines()]
            assert len(batch)==len(job['post_ids'])==state['result_count'] and {r['post_id'] for r in batch}==set(job['post_ids'])
            for row in batch:
                validate_result(row,posts[row['post_id']],config,manifest)
                assert row['post_id'] not in rows;rows[row['post_id']]=row
            receipts[jid]={'head':sha,'result_sha256':state['result_sha256']};counts['completed_jobs']+=1
    output=Path(output);ordered=[rows[p] for p in sorted(rows) if not is_exclusion(rows[p])];excluded=[rows[p] for p in sorted(rows) if is_exclusion(rows[p])]
    atomic_write(output/'labels.jsonl',b''.join(canonical(r) for r in ordered));atomic_write(output/'exclusions.jsonl',b''.join(canonical(r) for r in excluded))
    export(output,ordered)
    for r in ordered:
        counts['context_'+r['context']['state']]+=1;counts['posts_with_visual_failure']+=any(not i['viewed'] for i in r['images'])
    counts['policy_excluded_posts']=len(excluded)
    summary={'run_id':config['run_id'],'processed_posts':len(ordered),'resolved_posts':len(rows),'excluded_posts':len(excluded),'expected_posts':sum(len(j['post_ids']) for j in jobs.values()),'counts':dict(counts),'jobs':receipts,'note':'Schema validation is not a measurement of image-labeling accuracy.'}
    atomic_write(output/'receipt.json',canonical(summary))
    atomic_write(output/'review_queue.jsonl',b''.join(canonical({'post_id':r['post_id'],'flags':r['review_flags']}) for r in ordered if r['review_flags']))
    print(json.dumps(summary))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--config',required=True);p.add_argument('--output',required=True);p.add_argument('--remote');a=p.parse_args();collect(a.config,a.output,a.remote)
