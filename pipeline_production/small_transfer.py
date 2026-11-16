"""Additive, opt-in per-image transport. Does not claim jobs or write labels.

The publisher must already possess the pinned, screened source ZIP. Export is
local only; publishing assets is a separate authorized operation. Clients pass
an authenticated fetch callback (path, maximum bytes) -> bytes. No credentials,
URLs, changed policies, or queue identities are embedded in the transport.
"""
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import zipfile

from .bundles import unpack
from .common import atomic_write, canonical, digest
from .isolation import check_manifest


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def export_images(bundle, source, policy, destination):
    """Verify full upstream archive once, then stage single-image transfers.

    Never overwrite an export. Each image remains byte-for-byte identical;
    original manifest/post order and shared hashes remain unchanged.
    """
    destination = Path(destination)
    if destination.exists():
        raise ValueError('Export destination already exists')
    if Path(bundle).stat().st_size != source['bytes']:
        raise ValueError('Source size mismatch')
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.small-transfer-', dir=destination.parent))
    try:
        manifest = unpack(bundle, source, stage, policy)
        images = {}
        for post in manifest['posts']:
            for im in post['images']:
                path = stage / im['path']
                images[im['path']] = {'sha256': im['sha256'], 'bytes': path.stat().st_size}
        index = {'version': 1, 'source': {k: source[k] for k in
                 ('job_id', 'sha256', 'bytes', 'manifest_sha256', 'post_ids')},
                 'policy_sha256': _sha(canonical(policy)), 'images': images}
        atomic_write(stage / 'index.json', canonical(index))
        # Rename only after every original production check has passed.
        stage.rename(destination)
        return {'index_sha256': _sha(canonical(index)), 'images': len(images),
                'largest_image_bytes': max((x['bytes'] for x in images.values()), default=0)}
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def fetch_posts(fetch, index_raw, index_sha256, source, policy, post_ids, destination):
    """Fetch only selected whole posts plus transitive shared-hash peers.

    Callback is called once per image, sequentially. No archive download occurs.
    Index pin must come from the trusted exporter receipt, not from the index.
    An exception (including 401/403) propagates immediately: no retries/fallback.
    Existing verified image checkpoints are reused; mismatching files are never
    overwritten. No completion marker is written until all selected bytes pass.
    """
    if len(index_raw) > 1024 * 1024 or _sha(index_raw) != index_sha256:
        raise ValueError('Index size/hash mismatch')
    index = json.loads(index_raw)
    expected = {k: source[k] for k in ('job_id', 'sha256', 'bytes', 'manifest_sha256', 'post_ids')}
    if index['version'] != 1 or index['source'] != expected:
        raise ValueError('Wrong original source')
    if index['policy_sha256'] != _sha(canonical(policy)):
        raise ValueError('Wrong exclusion policy')
    raw = fetch('manifest.json', 1024 * 1024)
    if len(raw) > 1024 * 1024 or _sha(raw) != source['manifest_sha256']:
        raise ValueError('Original manifest mismatch')
    manifest = json.loads(raw)
    if manifest['job_id'] != source['job_id'] or [p['post_id'] for p in manifest['posts']] != source['post_ids']:
        raise ValueError('Original source posts mismatch')
    if manifest['split'] != 'production':
        raise ValueError('Not production source')
    check_manifest(manifest, policy)
    all_images = {i['path']: i['sha256'] for p in manifest['posts'] for i in p['images']}
    if set(index['images']) != set(all_images):
        raise ValueError('Image coverage mismatch')
    for path, sha in all_images.items():
        item = index['images'][path]
        if path != 'images/' + sha + '.jpg' or len(sha) != 64 or any(c not in '0123456789abcdef' for c in sha):
            raise ValueError('Unsafe image path/hash')
        if item['sha256'] != sha or type(item['bytes']) is not int or not 0 < item['bytes'] <= 128 * 1024 * 1024:
            raise ValueError('Invalid image metadata')
    selected = set(post_ids)
    if not selected or not selected <= set(source['post_ids']):
        raise ValueError('Unknown/empty post selection')
    while True:
        hashes = {i['sha256'] for p in manifest['posts'] if p['post_id'] in selected for i in p['images']}
        expanded = selected | {p['post_id'] for p in manifest['posts'] if any(i['sha256'] in hashes for i in p['images'])}
        if expanded == selected:
            break
        selected = expanded
    posts = [p for p in manifest['posts'] if p['post_id'] in selected]
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    receipt = {'version': 1, 'index_sha256': index_sha256, 'source': expected,
               'post_ids': [p['post_id'] for p in posts], 'policy_sha256': index['policy_sha256']}
    marker = destination / 'selection-receipt.json'
    if marker.exists() and marker.read_bytes() != canonical(receipt):
        raise ValueError('Destination belongs to another selection')
    for path in dict.fromkeys(i['path'] for p in posts for i in p['images']):
        item = index['images'][path]
        target = destination / path
        if target.exists():
            if target.stat().st_size != item['bytes'] or digest(target) != item['sha256']:
                raise ValueError('Existing checkpoint mismatch')
            continue
        data = fetch(path, item['bytes'])
        if len(data) != item['bytes'] or _sha(data) != item['sha256']:
            raise ValueError('Image checksum/size mismatch')
        atomic_write(target, data)
    atomic_write(marker, canonical(receipt))
    return posts
