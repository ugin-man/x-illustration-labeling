"""Freeze batch operations only; never rewrite an enabled revision."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline_production.common import canonical, digest, atomic_write, read_json
from ops_runtime_r5.control import verify_revision as verify_previous
from ops_batch.control import MANIFEST_PATH, CONTROL_PATH, MANUAL_PATH, REVISION, verify_revision


def main():
    control_path = ROOT / CONTROL_PATH
    if control_path.exists() and read_json(control_path)['state'] == 'enabled':
        raise SystemExit('Enabled revision is immutable')
    verified = verify_previous(ROOT, ROOT / 'runs/production-v4-001.json', require_enabled=False)
    files = list((ROOT / 'ops_batch').glob('*.py')) + [ROOT / MANUAL_PATH]
    manifest = dict(operations_revision=REVISION, base_run_id=verified['config']['run_id'],
        previous_manifest_sha256=verified['manifest_sha256'],
        files_sha256={p.relative_to(ROOT).as_posix(): digest(p) for p in files})
    atomic_write(ROOT / MANIFEST_PATH, canonical(manifest))
    atomic_write(control_path, canonical(dict(operations_revision=REVISION, state='blocked',
        manifest_sha256=digest(ROOT / MANIFEST_PATH), upgraded_worker_ids=[])))
    verify_revision(ROOT, ROOT / 'runs/production-v4-001.json', require_enabled=False)
    print(json.dumps(dict(manifest_sha256=digest(ROOT / MANIFEST_PATH),
        control_sha256=digest(control_path), pinned_files=len(files), state='blocked')))


if __name__ == '__main__':
    main()
