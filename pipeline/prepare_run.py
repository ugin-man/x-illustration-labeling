"""Explicitly freeze a new run after review; never overwrite an existing run config."""
import argparse
from pathlib import Path
from .common import atomic_write, canonical, digest, read_json
from .contract import VERSION
from .git_queue import safe_id

def prepare(run_id, split):
    root = Path(__file__).resolve().parents[1]
    target = root / 'runs' / (safe_id(run_id) + '.json')
    if target.exists():
        raise ValueError('Run already exists; use a new version')
    catalog = read_json(root / 'data/catalog.json')
    config = {'run_id': run_id, 'schema_version': VERSION, 'model_id': 'gpt-6.1-terra', 'reasoning_effort': 'high',
              'remote': 'https://github.com/ugin-man/x-illustration-labeling.git',
              'catalog_sha256': digest(root / 'data/catalog.json'),
              'manual_sha256': digest(root / 'review/terra_labeling_manual_draft.md'),
              'contract_sha256': digest(root / 'pipeline/contract.py'),
              'job_ids': [j['job_id'] for j in catalog['jobs'] if j['split'] == split], 'split': split}
    atomic_write(target, canonical(config))
    print(str(target))

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('run_id')
    p.add_argument('--split', choices=['calibration', 'evaluation', 'production'], default='calibration')
    a = p.parse_args()
    prepare(a.run_id, a.split)
