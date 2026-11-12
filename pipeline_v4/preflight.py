"""Network/storage probe only: download one calibration bundle, never infer labels."""
import json
import argparse
from pathlib import Path
from .bundles import download, unpack
from .common import read_json
from .worker import check_config, pinned_path, ROOT
from .launch_control import require_launch
from .isolation import load_policy

if __name__ == '__main__':
    # Do not send the old unfiltered image archive to a new cloud probe while screening is pending.
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    args = parser.parse_args()
    config, current_catalog = check_config(args.config)
    require_launch(config, current_catalog, ROOT)
    root = Path(__file__).resolve().parents[1]
    catalog = current_catalog
    job = next(j for j in catalog['jobs'] if j['job_id'] in config['job_ids'])
    folder = root / '.runtime/preflight'
    target = folder / job['asset']
    download(catalog, job, target, read_json(pinned_path(config,'assets_path','data/assets-v3.json')))
    manifest = unpack(target, job, folder, exclusion_policy=load_policy(config,root))
    print(json.dumps({'download_and_hashes': 'passed', 'image_paths': [str(folder / i['path']) for p in manifest['posts'][:3] for i in p['images']],
                      'note': 'Successful decode/download is not proof of model vision.'}))
