"""Materialize one named research snapshot from its verified files."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path


DATASETS = ('fixed-11543', 'additions-20261124')


def load(root, name):
    manifest = json.loads((root / name / 'manifest.json').read_text(encoding='utf-8'))
    if manifest['dataset'] != name:
        raise ValueError('Dataset ID mismatch')
    rows = {}
    for item in manifest['files']:
        path = (root / item['path']).resolve()
        if not path.is_relative_to((root / name).resolve()):
            raise ValueError('Dataset member outside its directory')
        if item.get('storage') == 'per-post-json':
            data = b''.join(p.read_bytes().rstrip(b'\n') + b'\n'
                            for p in sorted(path.glob('post-*.json')))
        else:
            data = path.read_bytes()
        if len(data) != item['bytes'] or hashlib.sha256(data).hexdigest() != item['sha256']:
            raise ValueError(f'Checksum mismatch: {path}')
        if path.name.endswith('.gz'):
            data = gzip.decompress(data)
        lines = [line for line in data.splitlines(keepends=True) if line.strip()]
        if len(lines) != item['records']:
            raise ValueError(f'Row count mismatch: {path}')
        for line in lines:
            post = json.loads(line)
            pid = post['post_id']
            if pid in rows:
                raise ValueError(f'Duplicate post: {pid}')
            rows[pid] = (line if line.endswith(b'\n') else line + b'\n',
                         post.get('record_type') == 'exclusion')
    if len(rows) != manifest['records']:
        raise ValueError('Dataset record count mismatch')
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', choices=(*DATASETS, 'combined'), default=DATASETS[0])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    rows = {}
    names = DATASETS if args.dataset == 'combined' else (args.dataset,)
    for name in names:
        selected = load(args.root.resolve(), name)
        if rows.keys() & selected.keys():
            raise ValueError('Selected snapshots contain overlapping posts')
        rows.update(selected)
    args.output.mkdir(parents=True, exist_ok=False)
    with (args.output / 'records.jsonl').open('wb') as all_rows, \
            (args.output / 'labels.jsonl').open('wb') as labels, \
            (args.output / 'exclusions.jsonl').open('wb') as exclusions:
        for raw, excluded in rows.values():
            all_rows.write(raw)
            (exclusions if excluded else labels).write(raw)
    print(json.dumps({'dataset': args.dataset, 'records': len(rows),
                      'labels': sum(not excluded for _, excluded in rows.values()),
                      'exclusions': sum(excluded for _, excluded in rows.values())}))


if __name__ == '__main__':
    main()
