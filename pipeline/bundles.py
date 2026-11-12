"""Private release downloads; credentials stay in process memory, never in URLs/files."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import urllib.request
from urllib.parse import urlsplit
import zipfile

from .common import atomic_write, digest
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
