"""Edit the selected draft without copying a post ID into each authoring script."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from ops_batch import worker
from ops_runtime_r5.queue import blocked_posts
from pipeline_production.common import atomic_write, canonical
from pipeline_production.git_queue import Conflict

ROOT = Path(__file__).resolve().parents[1]


def identity(row):
    return dict(post_id=row['post_id'], schema_version=row['schema_version'],
                provenance=row['provenance'], worker_id=row['execution']['worker_id'],
                started_at=row['execution']['started_at'],
                images=[(im['media_index'], im['sha256']) for im in row['images']])


@contextmanager
def edit_current(job, worker_id, config='runs/production-v4-001.json'):
    """Keep identity and original bytes; leave final label validation to save."""
    verified = worker.verify_revision(ROOT, config, worker_id)
    settings, catalog = verified['config'], verified['catalog']
    worker.base.require_launch(settings, catalog, ROOT)
    jobs = {j['job_id']: j for j in catalog['jobs'] if j['job_id'] in settings['job_ids']}
    runtime = ROOT / '.runtime' / settings['run_id']
    args = SimpleNamespace(job=job, worker=worker_id)
    with worker.helpers.local_lock(runtime, worker_id):
        folder, manifest, session = worker.load_local(args, settings, jobs, runtime)
        path = folder / 'draft.json'
        original = path.read_bytes()
        row = json.loads(original)
        pid = row['post_id']
        post = worker.helpers.require_post(manifest, pid, blocked_posts(manifest, worker.metadata_of(session)))
        expected_images = [(im['media_index'], im['sha256']) for im in post['images']]
        before = identity(row)
        if (pid != session.get('current_post') or before['worker_id'] != worker_id or
                before['provenance'] != worker.base.provenance(settings, manifest) or
                before['images'] != expected_images):
            raise Conflict('Draft identity differs from the selected post; preserve it and inspect before editing')
        rows = worker.active_rows(folder, manifest, settings, session)
        worker.helpers.guard_refusal(post, rows, manifest)
        if pid in rows:
            raise Conflict('Post already saved; use next or the existing revise workflow')
        # Serialize the identity so nested edits cannot mutate the comparison copy.
        frozen_identity = canonical(before)
        yield row
        edited = canonical(row)
        if canonical(identity(row)) != frozen_identity or path.read_bytes() != original:
            candidate = folder / '.batch' / 'edit-candidates' / (hashlib.sha256(edited).hexdigest() + '.json')
            atomic_write(candidate, edited)
            raise Conflict('Draft identity or file changed; original kept, candidate preserved at ' + str(candidate))
        if edited != original:
            backup = folder / '.batch' / 'draft-history' / (hashlib.sha256(original).hexdigest() + '.json')
            atomic_write(backup, original)
            atomic_write(path, edited)
        print(json.dumps(dict(edited_draft=pid, job_id=job, saved_result=False)))
