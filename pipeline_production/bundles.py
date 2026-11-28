"""Private release downloads; credentials stay in process memory, never in URLs/files."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import urllib.request
from urllib.parse import urlsplit
import zipfile

from .common import atomic_write, digest, canonical
from .isolation import check_manifest


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        host = urlsplit(newurl)
        if host.scheme != 'https' or host.hostname not in {'api.github.com', 'github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com'}:
            raise ValueError('Unexpected asset redirect host')
        out = super().redirect_request(req, fp, code, msg, headers, newurl)
        if out:
            out.remove_header('Authorization')
        return out


def token_from_existing_login():
    token = os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
    if token:
        return token
    env = dict(os.environ, GIT_TERMINAL_PROMPT='0', GCM_INTERACTIVE='never')
    p = subprocess.run(['git', 'credential', 'fill'], input=b'protocol=https\nhost=github.com\n\n',
                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env, timeout=20)
    if p.returncode == 0:
        values = dict(x.split('=', 1) for x in p.stdout.decode().splitlines() if '=' in x)
        if values.get('password'):
            return values['password']
    try:
        p = subprocess.run(['gh', 'auth', 'token'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=20)
        if p.returncode == 0:
            return p.stdout.decode().strip()
    except FileNotFoundError:
        pass
    return None


def download(catalog, job, target, assets):
    target = Path(target)
    if target.exists() and digest(target) == job['sha256']:
        return
    asset = assets[job['asset']]
    assert asset['size'] == job['bytes']
    url = f"https://api.github.com/repos/{catalog['repository']}/releases/assets/{int(asset['id'])}"
    headers = {'Accept': 'application/octet-stream', 'User-Agent': 'illustration-research/2', 'X-GitHub-Api-Version': '2022-11-28'}
    token = token_from_existing_login()
    if token:
        headers['Authorization'] = 'Bearer ' + token
    req = urllib.request.Request(url, headers=headers)
    opener = urllib.request.build_opener(SafeRedirect())
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_suffix('.download')
    try:
        with opener.open(req, timeout=60) as response, part.open('wb') as out:
            size = 0
            while chunk := response.read(1024 * 1024):
                size += len(chunk)
                if size > job['bytes']:
                    raise ValueError('Asset larger than pinned manifest')
                out.write(chunk)
        if size != job['bytes'] or digest(part) != job['sha256']:
            raise ValueError('Downloaded bundle hash/size mismatch')
        os.replace(part, target)
    finally:
        if part.exists():
            part.unlink()


def unpack(bundle, job, destination, exclusion_policy=None):
    destination = Path(destination)
    assert digest(bundle) == job['sha256'], 'Bundle hash mismatch'
    with zipfile.ZipFile(bundle) as z:
        mbytes = z.read('manifest.json')
        assert hashlib.sha256(mbytes).hexdigest() == job['manifest_sha256']
        manifest = json.loads(mbytes)
        assert manifest['job_id'] == job['job_id']
        assert [p['post_id'] for p in manifest['posts']] == job['post_ids']
        if exclusion_policy is not None:
            check_manifest(manifest, exclusion_policy)
        images = {i['path']: i['sha256'] for p in manifest['posts'] for i in p['images']}
        expected = set(images) | {'manifest.json'}
        assert set(z.namelist()) == expected and len(z.namelist()) == len(expected)
        assert sum(i.file_size for i in z.infolist()) <= 128 * 1024 * 1024
        for name, sha in images.items():
            assert name == 'images/' + sha + '.jpg' and len(sha) == 64
            data = z.read(name)
            assert hashlib.sha256(data).hexdigest() == sha
            atomic_write(destination / name, data)
        atomic_write(destination / 'manifest.json', mbytes)
    return manifest


def prepare_job(catalog, job, destination, assets, policy, bundle_dir=None):
    """Verify a screened archive and extract only the posts pinned for this run."""
    destination = Path(destination)
    manifest = job['manifest']
    if hashlib.sha256(canonical(manifest)).hexdigest() != job['manifest_sha256']:
        raise ValueError('Derived manifest checksum mismatch')
    check_manifest(manifest, policy)
    if manifest['split'] != 'production' or manifest['dataset_version'] != catalog['dataset_version']:
        raise ValueError('Job manifest belongs to a different production dataset')
    if len(job['sources']) != 1 or job['sources'][0]['job_id'] != job['job_id']:
        raise ValueError('Production requires exactly one self-contained source per job')
    if (job['sources'][0]['manifest_sha256'] != job['manifest_sha256']
            and not catalog.get('subset_of_catalog_sha256')):
        raise ValueError('Production source must match the exact pinned job manifest')
    wanted = {p['post_id']: p for p in manifest['posts']}
    if len(wanted) != len(manifest['posts']) or list(wanted) != job['post_ids']:
        raise ValueError('Derived post IDs mismatch')
    found = set()
    for source in job['sources']:
        target = Path(bundle_dir) / source['asset'] if bundle_dir else destination.parent / 'downloads' / source['asset']
        if not bundle_dir:
            download(catalog, source, target, assets)
        if digest(target) != source['sha256'] or target.stat().st_size != source['bytes']:
            raise ValueError('Screened source archive checksum/size mismatch')
        with zipfile.ZipFile(target) as z:
            raw = z.read('manifest.json')
            if hashlib.sha256(raw).hexdigest() != source['manifest_sha256']:
                raise ValueError('Screened source manifest mismatch')
            original = json.loads(raw)
            if (original['job_id'] != source['job_id'] or original['split'] != job['split']
                    or original['split'] != 'production'
                    or original['dataset_version'] != catalog['dataset_version']):
                raise ValueError('Only this pinned screened production source is permitted')
            if [p['post_id'] for p in original['posts']] != source['post_ids']:
                raise ValueError('Source post IDs mismatch')
            check_manifest(original, policy)
            images = {i['path']:i['sha256'] for p in original['posts'] for i in p['images']}
            if set(z.namelist()) != set(images)|{'manifest.json'} or len(z.namelist()) != len(images)+1:
                raise ValueError('Unexpected or duplicate archive members')
            if sum(i.file_size for i in z.infolist()) > 128*1024*1024:
                raise ValueError('Archive is too large')
            for post in original['posts']:
                if post['post_id'] not in wanted:continue
                if post != wanted[post['post_id']] or post['post_id'] in found:
                    raise ValueError('Subset differs from the screened source')
                found.add(post['post_id'])
                for im in post['images']:
                    if im['path'] != 'images/'+im['sha256']+'.jpg' or len(im['sha256']) != 64:
                        raise ValueError('Invalid image path')
                    data = z.read(im['path'])
                    if hashlib.sha256(data).hexdigest() != im['sha256']:
                        raise ValueError('Selected image checksum mismatch')
                    atomic_write(destination/im['path'], data)
    if found != set(wanted):raise ValueError('Subset post missing from screened sources')
    atomic_write(destination/'manifest.json', canonical(manifest))
    return manifest
