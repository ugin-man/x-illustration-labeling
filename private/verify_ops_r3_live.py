"""Verify collected metadata only. Never open research media or contact GitHub."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline_production import worker as base


def main():
    baseline = json.loads((ROOT / 'review/production-v4-001-ops-r3-baseline.json').read_bytes())
    live = json.loads((ROOT / 'review/production-v4-001-ops-r3-live-evidence.json').read_bytes())
    config, catalog = base.check_config(ROOT / 'runs/production-v4-001.json')
    policy = json.loads((ROOT / config['exclusion_policy_path']).read_bytes())
    excluded_ids = set(policy['post_ids'])
    excluded_hashes = set(policy['image_sha256'])
    jobs = {job['job_id']: job for job in catalog['jobs']}
    old = {w['worker']: w for w in baseline['workers']}
    results = []
    for item in live['workers']:
        worker = item['worker']
        assert worker in old
        prior = old[worker]
        assert item['job'] == prior['job'], 'Compare original job history before any handoff'
        files = {f['name']: f['sha'] for f in item['files']}
        assert all(files.get(f['name']) == f['sha'] for f in prior['files']), 'Accepted answer changed'
        manifest = jobs[item['job']]['manifest']
        posts = {post['post_id']: post for post in manifest['posts']}
        prior_names = {f['name'] for f in prior['files']}
        event_paths = {event['path'].replace('\\', '/') for event in item['image_events']}
        assert not any(Path(path).stem in excluded_hashes for path in event_paths)
        assert item['isolation_precedes_all_images'] is True
        assert item['next_returned_all_viewed_paths'] is True
        confirmed = []
        for row in item['new_rows']:
            pid = row['post_id']
            assert pid not in excluded_ids
            assert not any(im['sha256'] in excluded_hashes for im in row['images'])
            assert 'post-' + pid + '.json' not in prior_names
            assert 'post-' + pid + '.json' in files
            if row.get('record_type') == 'exclusion':
                continue
            assert row['execution']['worker_id'] == worker
            base.validate_result(row, posts[pid], config, manifest)
            if not all(im['viewed'] for im in row['images']):
                continue
            expected = {item['root'] + '/.runtime/' + config['run_id'] + '/' + item['job'] + '/' + im['path']
                        for im in posts[pid]['images']}
            if expected <= event_paths:
                confirmed.append(pid)
        assert len(set(confirmed)) >= 2, worker + ': fewer than two new pixel-viewed normal results'
        assert item['isolation_zero'] is True and item['ops_r3_commands_seen'] is True
        results.append(dict(worker=worker, job=item['job'], head=item['head'],
                            old_accepted_unchanged=len(prior['files']),
                            new_normal_posts=sorted(set(confirmed)),
                            actual_image_event_ids=[event['id'] for event in item['image_events']]))
    assert len(results) == 10 and {r['worker'] for r in results} == set(config['worker_ids'])
    assert len({r['job'] for r in results}) == 10
    out = dict(operations_revision='ops-r3', all_ten_saved_new_normal_posts=True,
               semantic_accuracy_audited=False, excluded_posts=len(excluded_ids),
               excluded_image_matches=0, only_cli_returned_images_viewed=True,
               workers=results)
    (ROOT / 'review/production-v4-001-ops-r3-live-verification.json').write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps(dict(verified_workers=len(results),
                         preserved_old_answers=sum(r['old_accepted_unchanged'] for r in results),
                         new_normal_posts=sum(len(r['new_normal_posts']) for r in results))))


if __name__ == '__main__':
    main()
