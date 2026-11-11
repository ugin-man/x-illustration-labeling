"""Network/storage probe only: download one calibration bundle, never infer labels."""
import json
from pathlib import Path
from .bundles import download, unpack
from .common import read_json

if __name__ == '__main__':
    root = Path(__file__).resolve().parents[1]
    catalog = read_json(root / 'data/catalog.json')
    job = next(j for j in catalog['jobs'] if j['split'] == 'calibration')
    folder = root / '.runtime/preflight'
    target = folder / job['asset']
    download(catalog, job, target, read_json(root / 'data/assets.json'))
    manifest = unpack(target, job, folder)
    print(json.dumps({'download_and_hashes': 'passed', 'image_paths': [str(folder / i['path']) for p in manifest['posts'][:3] for i in p['images']],
                      'note': 'Successful decode/download is not proof of model vision.'}))
