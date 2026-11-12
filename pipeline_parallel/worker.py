"""python -m pipeline_parallel.worker --help. This CLI handles I/O, never image inference."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random
import sys
import time

from . import contract_v4, context, disposition
from .bundles import download, unpack, prepare_job
from .common import atomic_write, canonical, digest, read_json
from .git_queue import Conflict, GitQueue, LostLease, QueueError, safe_id, ClaimBusy
from .launch_control import require_launch, require_no_source_data
from .toolchain import verify as verify_toolchain
from .isolation import load_policy, check_catalog, check_manifest, check_post_files

ROOT = Path(__file__).resolve().parents[1]


def schema_for(config):
    versions = {contract_v4.VERSION: contract_v4}
    if config['schema_version'] not in versions:
        raise ValueError('Unsupported schema version')
    return versions[config['schema_version']]


def pinned_path(config, key, default):
    path = (ROOT / config.get(key, default)).resolve()
    if not path.is_relative_to(ROOT.resolve()):
        raise ValueError('Pinned path must stay within the repository')
    return path


def check_config(path):
    if not __debug__:
        raise ValueError('Validation requires Python without -O')
    config = read_json(path)
    schema = schema_for(config)
    modern = schema.VERSION == contract_v4.VERSION
    catalog_path = pinned_path(config, 'catalog_path', 'data/catalog-v3.json' if modern else 'data/catalog.json')
    manual_path = pinned_path(config,'manual_path','docs/LABELING_V4_PARALLEL.md')
    catalog = read_json(catalog_path)
    assert digest(catalog_path) == config['catalog_sha256'], 'Catalog version changed'
    assert digest(manual_path) == config['manual_sha256'], 'Manual version changed'
    assert digest(ROOT / ('pipeline_parallel/contract_v4.py' if modern else 'pipeline_parallel/contract.py')) == config['contract_sha256'], 'Schema changed; create a new run'
    catalog_ids = [j['job_id'] for j in catalog['jobs']]
    post_ids = [p for j in catalog['jobs'] for p in j['post_ids']]
    assert len(catalog_ids)==len(set(catalog_ids)), 'Duplicate job ID'
    assert len(post_ids)==len(set(post_ids)), 'Duplicate post across jobs'
    assert config['job_ids'] and len(config['job_ids'])==len(set(config['job_ids'])), 'Empty or duplicate enabled jobs'
    assert set(config['job_ids']) <= set(catalog_ids)
    if modern:
        require_no_source_data(catalog)
        assert config.get('screening_receipt_sha256') == catalog['screening']['receipt_sha256']
        verify_toolchain(config, ROOT)
        check_catalog(catalog, load_policy(config, ROOT))
        assert len(config.get('worker_ids', [])) == config['max_workers'] == 3
        assert len(set(config['worker_ids'])) == 3
        for identity in config['worker_ids']: safe_id(identity)
        image_owners = {}
        for job in catalog['jobs']:
            assert hashlib.sha256(canonical(job['manifest'])).hexdigest() == job['manifest_sha256']
            assert job['manifest']['job_id'] == job['job_id']
            assert job['manifest']['dataset_version'] == catalog['dataset_version']
            assert [p['post_id'] for p in job['manifest']['posts']] == job['post_ids']
            check_manifest(job['manifest'], load_policy(config, ROOT))
            for post in job['manifest']['posts']:
                for im in post['images']:
                    assert image_owners.setdefault(im['sha256'],job['job_id']) == job['job_id'], 'Same image appears in different parallel jobs'
        assert all(j['split']==config['split'] for j in catalog['jobs'] if j['job_id'] in config['job_ids']), 'Do not mix calibration/evaluation/production'
    safe_id(config['run_id'])
    return config, catalog


def provenance(config, manifest):
    value = {k: config[k] for k in ('run_id', 'schema_version', 'catalog_sha256', 'manual_sha256', 'contract_sha256',
                                  'model_id', 'reasoning_effort')} | {'job_id': manifest['job_id']}
    if config['schema_version'] == contract_v4.VERSION:
        value['screening_receipt_sha256'] = config['screening_receipt_sha256']
    return value


def records_in(folder, manifest, config):
    by_id = {p['post_id']: p for p in manifest['posts']}
    out = {}
    for f in sorted((folder / 'results').glob('*.json')):
        pid = f.stem
        assert pid in by_id, 'A saved result does not belong to this job'
        row = read_json(f)
        validate_result(row,by_id[pid],config,manifest)
        out[pid] = row
    return out


def validate_result(row, post, config, manifest):
    if disposition.is_exclusion(row):
        return disposition.validate(row,post,provenance(config,manifest))
    return schema_for(config).validate(row,post,provenance(config,manifest))


def local_lease(lease):
    # This protects local work from expiry. Only remote checkpoint/finish accepts results.
    if lease.get('status') != 'leased' or lease['lease_until'] <= time.time():
        raise LostLease('Local reservation expired/released; preserve files and reacquire, never edit the lease')


def context_paths(folder, pid):
    return folder / 'context' / (pid+'.json'), folder / 'context' / (pid+'-budget.json')


def validate_draft(row, post, config, manifest, folder):
    validate_result(row,post,config,manifest)
    if disposition.is_exclusion(row):
        return  # No invented labels or context work for a refused input.
    if config['schema_version'] == contract_v4.VERSION:
        _, ledger = context_paths(folder, post['post_id'])
        measured = context.report(ledger)
        for key in ('searches','pages'):
            if row['context'][key] != measured[key]:
                raise ValueError('Context '+key+' differs from the per-post budget ledger')
        # elapsed_seconds is sampled when research ends, before writing a possibly long draft.
        if row['context']['elapsed_seconds'] > measured['elapsed_seconds'] + 1:
            raise ValueError('Context time exceeds the recorded ledger age')


def run(args):
    assert __debug__, 'Do not run with Python -O: validation must be enabled'
    config, catalog = check_config(args.config)
    schema = schema_for(config)
    jobs = {j['job_id']: j for j in catalog['jobs'] if j['job_id'] in config['job_ids']}
    runtime = ROOT / '.runtime' / config['run_id']
    remote = args.remote or config['remote']
    if args.command == 'contract':
        print(json.dumps(schema.definition(),ensure_ascii=False,indent=2))
        return
    if args.command in {'claim','next','save','checkpoint','finish','context'}:
        require_launch(config, catalog, ROOT)
    if args.command == 'claim':
        safe_id(args.worker)
        if args.worker not in config['worker_ids']:
            raise ValueError('This pilot permits only the three pinned worker identities')
        # Randomized per worker/run: avoid a herd competing for job 1.
        candidates = list(jobs.values())
        random.Random(config['run_id'] + args.worker).shuffle(candidates)
        with GitQueue(remote, config['run_id'], config['catalog_sha256']) as queue:
            try:
                queue.acquire_claim_gate(args.worker)
            except ClaimBusy:
                print(json.dumps({'status':'worker_claim_busy','instruction':'No reservation acquired. Retry once after at least 2 seconds, then report.'}))
                return
            known = queue.heads()
            for active_jid in sorted(set(known)&set(jobs)):
                _, active = queue.read(active_jid)
                if active['worker_id']==args.worker and active['status']=='leased' and active['lease_until']+120>time.time():
                    print(json.dumps({'status':'active_job_exists','job_id':active_jid,'instruction':'Resume your current job; do not start a second active job under the same worker identity.'}))
                    return
            candidates.sort(key=lambda j: j['job_id'] in known)
            for job in candidates:
                try:
                    lease = queue.reserve(job['job_id'], args.worker)
                except Conflict:
                    continue
                if not lease:
                    continue
                queue.release_claim_gate()
                folder = runtime / job['job_id']
                atomic_write(folder / 'lease.json', canonical(lease))
                try:
                    policy = load_policy(config, ROOT) if schema.VERSION == contract_v4.VERSION else None
                    manifest = prepare_job(catalog,job,folder,read_json(pinned_path(config,'assets_path','data/assets.json')),policy,bundle_dir=args.bundle_dir)
                    restored = queue.restore(job['job_id'], folder / 'results')
                    # Existing checkpoint results belong to the same pinned run, not worker ID.
                    records_in(folder, manifest, config)
                    print(json.dumps({'job_id': job['job_id'], 'folder': str(folder), 'restored': restored,
                                      'post_count': len(manifest['posts']), 'lease_until': lease['lease_until']}))
                    return
                except Exception:
                    queue.release(job['job_id'], lease['token'], 'input_preparation_failed')
                    raise
        print(json.dumps({'status': 'no_available_job', 'instruction': 'Stop. Retry in >= 120 seconds; do not spin.'}))
        return
    if args.command == 'status':
        with GitQueue(remote, config['run_id'], config['catalog_sha256']) as queue:
            heads = queue.heads()
            counts = {'unclaimed': len(set(jobs) - set(heads))}
            for job_id in sorted(set(jobs) & set(heads)):
                _, state = queue.read(job_id)
                key = state['status']
                if key == 'leased' and state['lease_until'] + 120 <= time.time():
                    key = 'expired'
                counts[key] = counts.get(key, 0) + 1
            print(json.dumps(counts))
        return
    if args.job not in jobs:
        raise ValueError('Job is not enabled in this run')
    job = jobs[args.job]
    folder = runtime / args.job
    lease = read_json(folder / 'lease.json')
    if args.command == 'release':
        # Cleanup must remain possible when preparation/schema validation failed or launch was stopped.
        with GitQueue(remote, config['run_id'], config['catalog_sha256']) as queue:
            sha = queue.release(args.job, lease['token'], 'worker_yielded')
        lease.update(status='available',lease_until=0,head=sha)
        atomic_write(folder/'lease.json',canonical(lease))
        print(json.dumps({'status':'release','remote_head':sha,'note':'Only checkpointed work can be recovered by another worker'}))
        return
    manifest = read_json(folder / 'manifest.json')
    assert digest(folder / 'manifest.json') == job['manifest_sha256']
    assert manifest['dataset_version']==catalog['dataset_version'], 'Manifest belongs to another dataset'
    if schema.VERSION == contract_v4.VERSION:
        check_manifest(manifest, load_policy(config, ROOT))
    if args.command not in {'validate','hold','exclude'}:
        local_lease(lease)
    if args.command == 'exclude':
        post = next((p for p in manifest['posts'] if p['post_id']==args.post),None)
        if post is None:
            raise ValueError('Exclusion requires --post from this job')
        if args.signal not in disposition.SIGNALS:
            raise ValueError('Use --signal model_refusal or image_tool_refusal only after an actual refusal')
        path = folder/'results'/(post['post_id']+'.json')
        if path.exists():
            row = read_json(path)
            validate_result(row,post,config,manifest)
            if not disposition.is_exclusion(row):
                raise Conflict('Existing classification cannot be overwritten; report it for a separate revision')
        else:
            row = disposition.create(post,provenance(config,manifest),lease['worker_id'],args.signal,args.media_index)
            # Persist the skip before network I/O. A retry sends only this same metadata.
            atomic_write(path,canonical(row))
        with GitQueue(remote, config['run_id'], config['catalog_sha256']) as queue:
            sha = queue.checkpoint(args.job,lease['token'],{post['post_id']:row},manifest=manifest)
            current = json.loads(queue.git('show',sha+':state.json').stdout)
            atomic_write(folder/'lease.json',canonical(dict(current,head=sha)))
        print(json.dumps({'excluded_post':post['post_id'],'temporary':True,'remote_head':sha,
                          'next':'next','instruction':'Do not reopen or retry this post. Continue with a different post only if the session and launch permit it.'}))
        return
    if args.command == 'context':
        if args.post not in {p['post_id'] for p in manifest['posts']}:
            raise ValueError('Post is not in this claimed job')
        saved = folder/'results'/(args.post+'.json')
        if saved.exists() and disposition.is_exclusion(read_json(saved)):
            raise ValueError('This post is excluded; do not fetch context or retry analysis')
        cache, ledger = context_paths(folder,args.post)
        action = args.context_action
        result = context.fetch(args.post,cache) if action=='fetch' else context.report(ledger) if action=='summary' else context.budget(ledger,action,query=getattr(args,'query',None))
        print(json.dumps(result,ensure_ascii=False))
        return
    rows = records_in(folder, manifest, config)
    if args.command == 'next':
        for post in manifest['posts']:
            if post['post_id'] in rows:
                continue
            if schema.VERSION == contract_v4.VERSION:
                check_post_files(folder, post, load_policy(config, ROOT))
            blocked={}
            for previous in runtime.glob('*/results/*.json'):
                saved=read_json(previous)
                if disposition.is_exclusion(saved):
                    prior_manifest=read_json(previous.parents[1]/'manifest.json')
                    prior_post=next(p for p in prior_manifest['posts'] if p['post_id']==saved['post_id'])
                    for im in prior_post['images']:blocked[im['sha256']]=saved['signal']
            duplicate=next((im for im in post['images'] if im['sha256'] in blocked),None)
            if duplicate:
                print(json.dumps({'status':'known_refusal_requires_exclusion','post_id':post['post_id'],'media_index':duplicate['media_index'],'signal':blocked[duplicate['sha256']], 'instruction':'Run exclude immediately using this metadata. No image paths are exposed.'}))
                return
            draft_path = folder / 'draft.json'
            draft = read_json(draft_path) if draft_path.exists() else None
            resumed = bool(draft and draft.get('post_id')==post['post_id'] and draft.get('provenance')==provenance(config,manifest)
                           and draft.get('execution',{}).get('worker_id')==lease['worker_id'])
            if not resumed:
                if draft and draft.get('post_id') not in rows:
                    atomic_write(folder/'unsent-drafts'/(hashlib.sha256(canonical(draft)).hexdigest()+'.json'),canonical(draft))
                draft = schema.template(post, provenance(config, manifest), worker_id=lease['worker_id'])
                atomic_write(draft_path, canonical(draft))
            print(json.dumps({'post_id': post['post_id'], 'images': [str(folder / i['path']) for i in post['images']],
                              'draft': str(draft_path), 'resumed_draft':resumed,
                              'lease_seconds_remaining':max(0,int(lease['lease_until']-time.time())),
                              'checkpoint_due':time.time()-lease['updated_at']>=600,
                              'instructions': 'View every image using an actual vision tool; complete bounded context; edit draft then validate/save. Checkpoint about every 10 minutes.'}))
            return
        print(json.dumps({'status': 'local_batch_complete', 'next': 'checkpoint, then finish'}))
        return
    if args.command in {'save','validate'}:
        row = read_json(args.input or folder / 'draft.json')
        if disposition.is_exclusion(row):
            raise ValueError('Use the dedicated exclude command; do not submit an exclusion as a research label')
        if row['execution']['finished_at'] is None:
            row['execution']['finished_at'] = datetime.now(timezone.utc).isoformat()
        post = next((p for p in manifest['posts'] if p['post_id'] == row['post_id']),None)
        if post is None:
            raise ValueError('Draft post is not in this job')
        validate_draft(row, post, config, manifest, folder)
        if row['execution']['worker_id'] != lease['worker_id']:
            raise ValueError('Draft belongs to another worker; do not submit their unfinished answer')
        if args.command == 'validate':
            print(json.dumps({'valid':True,'post_id':row['post_id'],'saved':False}))
            return
        path = folder / 'results' / (row['post_id'] + '.json')
        if path.exists() and path.read_bytes() != canonical(row):
            raise Conflict('Existing local answer differs; use a new review run')
        atomic_write(path, canonical(row))
        atomic_write(args.input or folder / 'draft.json', canonical(row))
        print(json.dumps({'saved_locally': row['post_id'], 'local_total': len(rows | {row['post_id']: row}),
                          'remote_accepted':False,'checkpoint_due':time.time()-lease['updated_at']>=600}))
        return
    with GitQueue(remote, config['run_id'], config['catalog_sha256']) as queue:
        if args.command in {'checkpoint','hold'}:
            # Restored accepted rows need no local search ledger. Newly authored rows do.
            posts_by_id = {p['post_id']:p for p in manifest['posts']}
            for pid in set(rows)-set(lease.get('completed_posts',[])):
                validate_draft(rows[pid],posts_by_id[pid],config,manifest,folder)
        if args.command == 'checkpoint':
            sha = queue.checkpoint(args.job, lease['token'], rows, manifest=manifest)
        elif args.command == 'finish':
            assert set(rows) == set(job['post_ids']), 'Local batch is incomplete'
            sha = queue.finish(args.job, lease['token'], job['post_ids'])
        elif args.command == 'hold':
            if args.post not in set(job['post_ids']):
                raise ValueError('Hold requires the affected --post from this job')
            sha = queue.checkpoint(args.job, lease['token'], rows, manifest=manifest,
                                   hold={'post_id':args.post,'reason':args.reason})
        else:
            raise ValueError('Unknown command')
        current = json.loads(queue.git('show',sha+':state.json').stdout)
        atomic_write(folder/'lease.json',canonical(dict(current,head=sha)))
        print(json.dumps({'status': args.command, 'remote_head': sha,'lease_until':current['lease_until']}))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config', help='Required for job operations; no implicit old pilot run')
    p.add_argument('--remote', help='Testing only: override remote with a local bare repository')
    p.add_argument('command', choices=['contract', 'claim', 'next', 'validate', 'save', 'checkpoint', 'finish', 'release', 'status','context','hold','exclude'])
    p.add_argument('--worker', default='worker-01')
    p.add_argument('--job')
    p.add_argument('--input')
    p.add_argument('--bundle-dir')
    p.add_argument('--post')
    p.add_argument('--query',help='Exactly one additional search query; reserve once per query before using a search tool')
    p.add_argument('--signal',choices=sorted(disposition.SIGNALS))
    p.add_argument('--media-index',type=int,help='Refused image index if known; do not reopen the image to find it')
    p.add_argument('--context-action',choices=['fetch','budget','search','page','summary'],default='fetch')
    p.add_argument('--reason',choices=['input_requires_review','image_unavailable','schema_ambiguity'],default='input_requires_review')
    args = p.parse_args()
    if args.command=='contract' and not args.config:
        print(json.dumps(contract_v4.definition(),ensure_ascii=False,indent=2))
        return
    if not args.config:
        p.error('--config is required; do not use the old unfiltered pilot implicitly')
    try:
        run(args)
    except (AssertionError, ValueError, KeyError, TypeError, AttributeError, Conflict, LostLease, QueueError, OSError) as e:
        print(json.dumps({'error': type(e).__name__, 'message': str(e) or 'Draft schema validation failed; compare required fields and values with the pinned contract.'}), file=sys.stderr)
        raise SystemExit(2)


if __name__ == '__main__':
    main()
