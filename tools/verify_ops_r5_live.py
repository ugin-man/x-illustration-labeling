"""Verify collected metadata; never open media, change labels, or use the network."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline_production import worker as base


def main():
    read = lambda name: json.loads((ROOT / 'review' / name).read_bytes())
    baseline = read('production-v4-001-ops-r5-baseline.json')
    live = read('production-v4-001-ops-r5-live-evidence.json')
    config, catalog = base.check_config(ROOT / 'runs/production-v4-001.json')
    policy = json.loads((ROOT / config['exclusion_policy_path']).read_bytes())
    excluded_ids, excluded_hashes = set(policy['post_ids']), set(policy['image_sha256'])
    jobs = {job['job_id']: job for job in catalog['jobs']}
    prior = {w['worker']: w for w in baseline['workers']}
    verified = []
    for item in live['workers']:
        worker = item['worker']; old = prior[worker]
        assert item['job'] == old['job']
        files = {f['name']: f['sha'] for f in item['files']}
        assert all(files.get(f['name']) == f['sha'] for f in old['files']), 'Accepted bytes changed'
        manifest = jobs[item['job']]['manifest']
        posts = {p['post_id']: p for p in manifest['posts']}
        old_ids = {f['name'][5:-5] for f in old['files']}
        events = {event['path'].replace('\\', '/') for event in item['image_events']}
        assert not any(Path(p).stem in excluded_hashes for p in events)
        assert item['isolation_precedes_all_images'] and item['next_returned_all_viewed_paths']
        assert item['isolation_zero'] and item['ops_r5_commands_seen']
        confirmed = []
        for row in item['new_rows']:
            pid = row['post_id']
            assert pid not in excluded_ids and pid not in old_ids
            assert 'post-' + pid + '.json' in files
            assert row.get('record_type') != 'exclusion'
            assert row['execution']['worker_id'] == worker
            assert not any(im['sha256'] in excluded_hashes for im in row['images'])
            base.validate_result(row, posts[pid], config, manifest)
            assert all(im['viewed'] for im in row['images'])
            paths = {item['root'] + '/.runtime/' + config['run_id'] + '/' + item['job'] + '/' + im['path']
                     for im in posts[pid]['images']}
            assert paths <= events, 'No fresh actual image tool event for this post'
            assert pid not in set(item['preexisting_unsubmitted_ids']), 'Recovered output is not fresh processing'
            confirmed.append(pid)
        assert len(set(confirmed)) >= 2
        verified.append(dict(worker=worker, job=item['job'], head=item['head'],
                             preserved_old_results=len(old['files']), new_normal_posts=sorted(set(confirmed)),
                             actual_image_event_ids=[e['id'] for e in item['image_events']]))
    assert len(verified) == 10 and {r['worker'] for r in verified} == set(config['worker_ids'])
    assert len({r['job'] for r in verified}) == 10
    assert live['preserved_other_job_results'] is True
    result = dict(revision='ops-r5', all_ten_processed_and_remotely_saved=True,
                  prior_total_preserved=baseline['accepted_total'], semantic_accuracy_audited=False,
                  excluded_posts=len(excluded_ids), excluded_image_matches=0, workers=verified)
    (ROOT / 'review/production-v4-001-ops-r5-live-verification.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps(dict(verified_workers=10, preserved_prior_total=baseline['accepted_total'],
                         new_normal_posts=sum(len(w['new_normal_posts']) for w in verified))))


if __name__ == '__main__':
    main()
