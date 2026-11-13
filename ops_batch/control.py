"""Pin the new operational boundary and its unchanged r5 dependencies."""
from pathlib import Path
from ops_runtime_r5 import control as previous

REVISION = 'ops-batch-v1'
MANIFEST_PATH = 'ops/revisions/production-v4-001-ops-batch-v1.json'
CONTROL_PATH = 'ops/ops-batch-v1-control.json'
MANUAL_PATH = 'docs/WORKER_BATCH.md'


def verify_revision(root, config_path, worker=None, require_enabled=True):
    root = Path(root).resolve()
    verified = previous.verify_revision(root, config_path, worker, require_enabled=False)
    manifest = previous.read_object(root / MANIFEST_PATH)
    expected = {p.relative_to(root).as_posix() for p in (root / 'ops_batch').glob('*.py')} | {MANUAL_PATH}
    if (manifest.get('operations_revision') != REVISION or
            manifest.get('previous_manifest_sha256') != verified['manifest_sha256'] or
            manifest.get('base_run_id') != verified['config']['run_id'] or
            set(manifest.get('files_sha256', {})) != expected):
        raise ValueError('Batch revision or pinned dependency differs')
    for name, sha in manifest['files_sha256'].items():
        if previous.sha256(previous.contained(root, name)) != sha:
            raise ValueError('Batch code/manual differs from fixed revision: ' + name)
    control = previous.read_object(root / CONTROL_PATH)
    if (control.get('operations_revision') != REVISION or
            control.get('manifest_sha256') != previous.sha256(root / MANIFEST_PATH) or
            control.get('state') not in {'blocked', 'enabled'}):
        raise ValueError('Batch activation differs')
    if require_enabled and (control['state'] != 'enabled' or
            set(control.get('upgraded_worker_ids', [])) != set(verified['config']['worker_ids'])):
        raise ValueError('All ten workers must switch before batch operations start')
    return dict(verified, batch_manifest=manifest, batch_control=control)
