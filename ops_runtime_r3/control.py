"""Verify the additive operations revision without changing frozen inputs."""
import hashlib
import json
from pathlib import Path
import re

from pipeline_production import worker as base


REVISION = 'ops-r3'
BASE_COMMIT = '4d2c98374a1364faf1e2b546a4c460e80e9b2903'
MANIFEST_PATH = 'ops/revisions/production-v4-001-ops-r3.json'
CONTROL_PATH = 'ops/ops-r3-control.json'
MANUAL_PATH = 'docs/WORKER_OPERATIONS_R3.md'
COORDINATOR_IDS = ('ops-coordinator',)


def contained(root, relative):
    if not isinstance(relative, str) or not relative or '\\' in relative:
        raise ValueError('Operations paths must be nonempty relative POSIX paths')
    path = Path(relative)
    if path.is_absolute() or '..' in path.parts or ':' in relative:
        raise ValueError('Operations path must remain inside the checkout')
    resolved = (root / path).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError('Operations path escaped the checkout')
    return resolved


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_object(path):
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError('Operations metadata must be a JSON object')
    return value


def verify_revision(root, config_path, worker_id=None, *, require_enabled=True,
                    coordinator=False):
    """Return verified metadata; never mutate configuration, queues, or files.

    Tests may use a temporary checkout with its own pinned base configuration.
    The frozen base validator remains authoritative in both cases.
    """
    root = Path(root).resolve()
    if Path(base.ROOT).resolve() != root:
        raise ValueError('Operations and frozen runtime must use the same checkout')
    config_path = Path(config_path)
    if not config_path.is_absolute():
        config_path = root / config_path
    config_path = config_path.resolve()
    if not config_path.is_relative_to(root):
        raise ValueError('Run configuration must remain inside the checkout')

    manifest_path = contained(root, MANIFEST_PATH)
    manifest = read_object(manifest_path)
    if manifest.get('operations_revision') != REVISION:
        raise ValueError('Unsupported operations revision')
    if manifest.get('base_commit') != BASE_COMMIT:
        raise ValueError('Operations revision names a different frozen base')
    if manifest.get('base_config_sha256') != sha256(config_path):
        raise ValueError('Frozen run configuration differs from operations manifest')
    if 'base_config_path' in manifest:
        if contained(root, manifest['base_config_path']) != config_path:
            raise ValueError('Run path differs from operations manifest')

    # These checks retain all original classification, catalog, exclusion,
    # launch-contract and frozen toolchain pins. Do not replace them with an
    # operations-only schema or an optimized/unvalidated code path.
    config, catalog = base.check_config(config_path)
    if manifest.get('base_run_id') != config['run_id']:
        raise ValueError('Operations revision belongs to another run')
    if manifest.get('classification_manual_sha256') != config['manual_sha256']:
        raise ValueError('Classification manual changed in operations revision')
    if ('classification_contract_sha256' in manifest and
            manifest['classification_contract_sha256'] != config['contract_sha256']):
        raise ValueError('Classification schema changed in operations revision')

    required = {MANUAL_PATH}
    required.update(p.relative_to(root).as_posix()
                    for p in (root / 'ops_runtime_r3').rglob('*.py'))
    minimum = {'ops_runtime_r3/__init__.py', 'ops_runtime_r3/control.py',
               'ops_runtime_r3/queue.py', 'ops_runtime_r3/worker.py', MANUAL_PATH}
    hashes = manifest.get('files_sha256')
    if not isinstance(hashes, dict) or set(hashes) != required or not minimum <= required:
        raise ValueError('Operations manifest must pin every module and the operations manual')
    for name, expected in hashes.items():
        if not isinstance(expected, str) or not re.fullmatch(r'[0-9a-f]{64}', expected):
            raise ValueError('Invalid operations file hash')
        if sha256(contained(root, name)) != expected:
            raise ValueError('Operations code/manual differs from its fixed revision: ' + name)

    control = read_object(contained(root, CONTROL_PATH))
    manifest_hash = sha256(manifest_path)
    if (control.get('operations_revision') != REVISION or
            control.get('base_run_id') != config['run_id'] or
            control.get('manifest_sha256') != manifest_hash):
        raise ValueError('Activation control differs from the pinned operations revision')
    if control.get('state') not in {'blocked', 'enabled'}:
        raise ValueError('Invalid operations activation state')
    worker_ids = config['worker_ids']
    upgraded = control.get('upgraded_worker_ids')
    if (not isinstance(upgraded, list) or
            any(not isinstance(w, str) for w in upgraded) or
            len(upgraded) != len(set(upgraded)) or not set(upgraded) <= set(worker_ids)):
        raise ValueError('Invalid upgraded worker list')
    if (control['state'] == 'enabled' and
            (len(worker_ids) != 10 or set(upgraded) != set(worker_ids))):
        raise ValueError('All ten workers must be upgraded before enabling operations')
    if control.get('coordinator_ids') != list(COORDINATOR_IDS):
        raise ValueError('Unexpected coordinator identity in operations control')
    if require_enabled and control['state'] != 'enabled':
        raise ValueError('Operations revision is blocked pending the coordinated rollout')

    if coordinator:
        if worker_id not in COORDINATOR_IDS:
            raise ValueError('This operation requires the explicit coordinator identity')
    elif worker_id is not None and worker_id not in worker_ids:
        raise ValueError('Worker identity is outside the pinned ten-worker scope')
    elif require_enabled and worker_id is None:
        raise ValueError('An explicit worker identity is required')
    return {'manifest': manifest, 'control': control, 'config': config,
            'catalog': catalog, 'manifest_sha256': manifest_hash}
