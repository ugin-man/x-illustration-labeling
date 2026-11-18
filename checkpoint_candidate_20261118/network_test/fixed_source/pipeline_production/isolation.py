"""Metadata/byte checks only. Never display or decode an excluded image."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile
from .common import atomic_write, canonical, digest, read_json


def prepare_policy(root, catalog):
    receipt = read_json(root / 'private/screening/screening-receipt.json')
    fingerprint = receipt.pop('receipt_sha256')
    if (hashlib.sha256(canonical(receipt)).hexdigest() != fingerprint
            or fingerprint != catalog['screening']['receipt_sha256'] or receipt['state'] != 'complete'):
        raise ValueError('Screening receipt mismatch')
    policy = {'version': 1, 'screening_receipt_sha256': fingerprint,
              'post_ids': sorted(receipt['effective_excluded_ids']),
              'image_sha256': sorted(receipt['excluded_image_sha256'])}
    path = root / 'data/exclusions' / (fingerprint + '.json')
    if path.exists() and read_json(path) != policy:
        raise ValueError('Do not overwrite a frozen exclusion policy')
    atomic_write(path, canonical(policy))
    return path


def load_policy(config, root):
    if not config.get('exclusion_policy_path') or not config.get('exclusion_policy_sha256'):
        raise ValueError('Pinned exclusion policy is required')
    root = Path(root).resolve()
    path = (root / config['exclusion_policy_path']).resolve()
    if not path.is_relative_to(root) or digest(path) != config['exclusion_policy_sha256']:
        raise ValueError('Exclusion policy changed or escaped workspace')
    policy = read_json(path)
    if (set(policy) != {'version','screening_receipt_sha256','post_ids','image_sha256'} or policy['version'] != 1
            or policy['screening_receipt_sha256'] != config['screening_receipt_sha256']):
        raise ValueError('Exclusion policy does not match screened run')
    for field, pattern in [('post_ids',r'[0-9]+'),('image_sha256',r'[0-9a-f]{64}')]:
        values = policy[field]
        if not isinstance(values,list) or len(values)!=len(set(values)) or not all(isinstance(v,str) and re.fullmatch(pattern,v) for v in values):
            raise ValueError('Invalid exclusion policy')
    return policy


def check_catalog(catalog, policy):
    if set(policy['post_ids']).intersection(p for j in catalog['jobs'] for p in j['post_ids']):
        raise ValueError('Excluded post found in catalog; do not reserve or view')


def check_manifest(manifest, policy):
    posts, hashes = set(policy['post_ids']), set(policy['image_sha256'])
    for p in manifest['posts']:
        if p['post_id'] in posts or any(i['sha256'] in hashes for i in p['images']):
            raise ValueError('Excluded post/image found; do not extract or view')


def check_post_files(folder, post, policy):
    check_manifest({'posts':[post]},policy)
    folder = Path(folder).resolve()
    for im in post['images']:
        path = (folder / im['path']).resolve()
        if not path.is_relative_to(folder) or digest(path) != im['sha256']:
            raise ValueError('Image bytes/path differ from approved input; do not view')


def audit_workspace(root, policy):
    """Check existing image caches and ZIP entries as opaque bytes, without pixels."""
    root = Path(root).resolve()
    forbidden = set(policy['image_sha256'])
    checked_files = checked_entries = 0
    for path in root.rglob('*'):
        if not path.is_file() or '.git' in path.relative_to(root).parts:
            continue
        if path.suffix.lower() in {'.jpg','.jpeg','.png','.webp','.gif'}:
            checked_files += 1
            if digest(path) in forbidden:
                raise ValueError('Excluded image exists in workspace; do not view any research image')
        elif path.suffix.lower() == '.zip':
            with zipfile.ZipFile(path) as archive:
                for info in archive.infolist():
                    if Path(info.filename).suffix.lower() not in {'.jpg','.jpeg','.png','.webp','.gif'}:
                        continue
                    checked_entries += 1
                    with archive.open(info) as source:
                        h = hashlib.sha256()
                        while chunk := source.read(1024*1024):
                            h.update(chunk)
                    if h.hexdigest() in forbidden:
                        raise ValueError('Excluded image exists in workspace archive; do not view')
    return {'workspace':str(root),'loose_images_checked':checked_files,'archive_images_checked':checked_entries,'excluded_images_found':0}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',required=True,type=Path)
    parser.add_argument('--workspace',required=True,type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    config = read_json(args.config)
    print(json.dumps(audit_workspace(args.workspace,load_policy(config,root))))
