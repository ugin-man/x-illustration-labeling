"""Explicitly freeze a new run after review; never overwrite an existing run config."""
import argparse
from pathlib import Path
from .common import atomic_write, canonical, digest, read_json
from .contract_v4 import VERSION
from .git_queue import safe_id
from .launch_control import require_no_source_data, verify_local_screening
from .toolchain import fingerprint
from .isolation import prepare_policy

def prepare(run_id, split, root=None, catalog_path=None):
    root = Path(root or Path(__file__).resolve().parents[1])
    target = root / 'runs' / (safe_id(run_id) + '.json')
    if target.exists():
        raise ValueError('Run already exists; use a new version')
    if not catalog_path or split != 'production':
        raise ValueError('An explicit screened production catalog and production split are required')
    catalog_path = (root / catalog_path).resolve()
    if not catalog_path.is_relative_to(root.resolve()):
        raise ValueError('Catalog must be inside the repository')
    if not catalog_path.exists():
        raise ValueError('人間の事前確認と、除外を反映した新規入力バッチの作成が先です。')
    catalog = read_json(catalog_path)
    versioned = root / 'data/catalogs' / (catalog['dataset_version']+'.json')
    if versioned.exists() and digest(versioned)==digest(catalog_path):
        catalog_path = versioned.resolve()
    require_no_source_data(catalog)
    verify_local_screening(catalog, root)
    exclusion_path = prepare_policy(root, catalog)
    config = {'run_id': run_id, 'schema_version': VERSION, 'model_id': 'gpt-6.1-terra', 'reasoning_effort': 'high',
              'remote': 'https://github.com/ugin-man/x-illustration-labeling.git',
              'catalog_path': catalog_path.relative_to(root.resolve()).as_posix(), 'assets_path': catalog['assets_path'],
              'catalog_sha256': digest(catalog_path),
              'manual_path':'docs/LABELING_V4_PRODUCTION.md', 'worker_manual_path':'docs/WORKER_PRODUCTION.md',
              'manual_sha256': digest(root / 'docs/LABELING_V4_PRODUCTION.md'),
              'contract_sha256': digest(root / 'pipeline_production/contract_v4.py'),
              'screening_receipt_sha256': catalog['screening']['receipt_sha256'],
              'exclusion_policy_path': exclusion_path.relative_to(root).as_posix(),
              'exclusion_policy_sha256': digest(exclusion_path),
              'job_ids': [j['job_id'] for j in catalog['jobs'] if j['split'] == split], 'split': split,
              'toolchain_sha256': fingerprint(root), 'max_workers':10, 'batch_size':50, 'queue_version':'dispatch-v1',
              'max_posts':sum(len(j['post_ids']) for j in catalog['jobs'] if j['split']==split),
              'worker_ids':['terra-prod-%02d' % i for i in range(1,11)]}
    if not config['job_ids']:
        raise ValueError('No screened posts remain in this split; do not create an empty run')
    atomic_write(target, canonical(config))
    print(str(target))
    return config

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('run_id')
    p.add_argument('--split', choices=['production'], default='production')
    p.add_argument('--catalog', required=True, help='Versioned screened production catalog inside the repository')
    a = p.parse_args()
    prepare(a.run_id, a.split, catalog_path=a.catalog)
