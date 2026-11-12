"""Read-only recovery of the bounded parallel pilot for local human review."""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen
import webbrowser

from .common import canonical,read_json
from .worker import check_config,validate_result,ROOT
from .bundles import prepare_job
from .isolation import load_policy,check_post_files
from .disposition import is_exclusion
from pipeline_v4.review_app import ReviewServer


def load_pilot(config_path=None,recovered=None):
    config,catalog=check_config(config_path or ROOT/'runs/parallel-v4-001.json')
    folder=Path(recovered) if recovered else ROOT/'.runtime/recovered'/config['run_id']
    policy=load_policy(config,ROOT);rows={};paths={};excluded=[]
    source=read_json(ROOT/'data/catalogs/data-v3-7113eaaefc38.json')
    bundle_dir=ROOT/'dist'/source['dataset_version']
    for job in catalog['jobs']:
        if job['job_id'] not in config['job_ids']:continue
        base=folder/job['job_id'];state=read_json(base/'state.json');raw=(base/'labels.jsonl').read_bytes()
        if state['status']!='completed' or state['run_id']!=config['run_id'] or hashlib.sha256(raw).hexdigest()!=state['result_sha256']:
            raise ValueError('Completed result checksum/identity mismatch')
        manifest_raw=(base/'manifest.json').read_bytes()
        if hashlib.sha256(manifest_raw).hexdigest()!=job['manifest_sha256']:
            raise ValueError('Pinned manifest mismatch')
        destination=ROOT/'.runtime/review-images'/config['run_id']/job['job_id']
        manifest=prepare_job(catalog,job,destination,{},policy,bundle_dir=bundle_dir)
        posts={p['post_id']:p for p in manifest['posts']};batch=[json.loads(line) for line in raw.splitlines()]
        if len(batch)!=len(posts) or {r['post_id'] for r in batch}!=set(posts):raise ValueError('Result coverage mismatch')
        for row in batch:
            post=posts[row['post_id']];validate_result(row,post,config,manifest)
            if is_exclusion(row):excluded.append({'post_id':row['post_id'],'reason':row['reason']});continue
            check_post_files(destination,post,policy)
            if row['post_id'] in rows:raise ValueError('Duplicate post across jobs')
            rows[row['post_id']]=row
            for im in post['images']:paths[im['sha256']]=destination/im['path']
    ordered=[rows[p] for p in sorted(rows)]
    note_path=ROOT/'review/parallel-v4-001_audit_notes.json'
    notes=read_json(note_path).get('posts',{}) if note_path.exists() else {}
    for row in ordered:
        if row['post_id'] in notes:row['coordinator_notes']=notes[row['post_id']]
    fingerprint=hashlib.sha256(b''.join(canonical(r) for r in ordered)).hexdigest()
    return {'run_id':config['run_id'],'schema_version':config['schema_version'],'posts':ordered,'fingerprint':fingerprint,'exclusions':excluded},paths


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--port',type=int,default=8768);p.add_argument('--open',action='store_true');a=p.parse_args()
    if a.open:
        try:
            with urlopen(f'http://127.0.0.1:{a.port}/api/health',timeout=1) as r:health=json.load(r)
            if health.get('run_id')=='parallel-v4-001':webbrowser.open(f'http://127.0.0.1:{a.port}');return
        except (OSError,ValueError):pass
    data,images=load_pilot();server=ReviewServer(('127.0.0.1',a.port),data,images,ROOT/'private/reviews'/(data['run_id']+'.json'))
    url=f'http://127.0.0.1:{a.port}';print(f'{url} | {len(data["posts"])} posts | {len(images)} images',flush=True)
    if a.open:webbrowser.open(url)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()


if __name__=='__main__':main()
