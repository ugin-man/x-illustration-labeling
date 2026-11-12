"""Build NEW input bundles only after complete human screening. Does not upload or launch."""
import argparse
import hashlib
from pathlib import Path
import zipfile

from .common import atomic_write, canonical, digest, read_json
from .screening import ROOT, ScreeningStore, build_index
from .human_source import bundle_root


def build(root=ROOT):
    index = build_index(root)
    store = ScreeningStore(root / 'private/screening/data-v1.sqlite3', index)
    receipt = store.completed_receipt()
    allowed = set(receipt['included_post_ids'])
    forbidden = set(receipt['excluded_image_sha256'])
    if not allowed:
        raise ValueError('No included posts remain')
    version = 'data-v3-' + receipt['receipt_sha256'][:12]
    output = root / 'dist' / version
    catalog_target = root / 'data/catalog-v3.json'
    versioned_catalog = root / 'data/catalogs' / (version+'.json')
    if output.exists() or versioned_catalog.exists():
        raise ValueError('Prepared output already exists; do not overwrite a frozen input catalog')
    source = read_json(root / 'data/catalog.json')
    by_id = {p['post_id']:p for p in index['posts']}
    output.mkdir(parents=True)
    jobs, unique = [], set()
    for old in source['jobs']:
        selected = [by_id[p] for p in old['post_ids'] if p in allowed]
        if not selected:
            continue
        jid = 's3-' + old['job_id']
        posts = [{'post_id':p['post_id'],'images':p['images']} for p in selected]
        assert not any(im['sha256'] in forbidden for p in posts for im in p['images'])
        manifest = {'dataset_version':version,'job_id':jid,'split':old['split'],'posts':posts}
        raw_manifest = canonical(manifest)
        target = output / (jid + '.zip')
        with zipfile.ZipFile(bundle_root(root)/old['asset']) as original, zipfile.ZipFile(target.with_suffix('.part'),'w',compression=zipfile.ZIP_STORED) as z:
            def put(name, data):
                info = zipfile.ZipInfo(name, date_time=(2026,11,12,0,0,0))
                info.external_attr = 0o100644 << 16
                z.writestr(info,data)
            put('manifest.json',raw_manifest)
            for name in sorted({im['path'] for p in posts for im in p['images']}):
                data = original.read(name)
                sha = hashlib.sha256(data).hexdigest()
                if sha != Path(name).stem or sha in forbidden:
                    raise ValueError('Source hash or exclusion mismatch')
                unique.add(sha)
                put(name,data)
        target.with_suffix('.part').replace(target)
        jobs.append({'job_id':jid,'split':old['split'],'post_ids':[p['post_id'] for p in posts],
                     'asset':target.name,'bytes':target.stat().st_size,'sha256':digest(target),
                     'manifest_sha256':hashlib.sha256(raw_manifest).hexdigest(),'image_references':sum(len(p['images']) for p in posts)})
    if store.completed_receipt()['receipt_sha256'] != receipt['receipt_sha256']:
        raise ValueError('Screening changed while building; output is not publishable and no catalog was activated')
    catalog = {'dataset_version':version,'release_tag':version,'repository':source['repository'],
               'post_count':len(allowed),'image_references':sum(j['image_references'] for j in jobs),'unique_images':len(unique),
               'source_catalog_sha256':index['catalog_sha256'],'jobs':jobs,
               'screening':{'state':'complete','receipt_sha256':receipt['receipt_sha256'],'review_revision':receipt['revision'],
                            'source_catalog_sha256':index['catalog_sha256'],'counts':receipt['counts']}}
    atomic_write(output/'catalog.json',canonical(catalog))
    atomic_write(versioned_catalog,canonical(catalog))
    atomic_write(catalog_target,canonical(catalog))
    store.write_export()
    print(f'{version}: {len(allowed)} posts; prepared locally only. Production is still blocked.')
    return catalog


if __name__ == '__main__':
    argparse.ArgumentParser(description=__doc__).parse_args()
    build()
