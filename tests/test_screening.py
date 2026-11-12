import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import zipfile

from pipeline.common import atomic_write, canonical, digest
from pipeline.screening import ScreeningStore, build_index
from pipeline.screening_app import ScreeningServer
from pipeline.prepare_screened import build
from pipeline.launch_control import require_launch, verify_local_screening


def source_fixture(root):
    data = {letter: ('synthetic image ' + letter).encode() for letter in 'ABCD'}
    images = {k:{'sha256':hashlib.sha256(v).hexdigest(),'path':'images/'+hashlib.sha256(v).hexdigest()+'.jpg'} for k,v in data.items()}
    posts = [{'post_id':str(i+1),'images':[dict(images[k],media_index=n+1) for n,k in enumerate(keys)]} for i,keys in enumerate(['A','AB','C','D'])]
    folder = root / 'dist/data-v1'
    folder.mkdir(parents=True)
    jobs = []
    for n,batch in enumerate([posts[:2],posts[2:]],1):
        jid=f'cal-{n:04d}'
        manifest={'dataset_version':'data-v1','job_id':jid,'split':'calibration','posts':batch}
        raw=canonical(manifest)
        path=folder/(jid+'.zip')
        with zipfile.ZipFile(path,'w') as z:
            z.writestr('manifest.json',raw)
            for sha in {i['sha256'] for p in batch for i in p['images']}:
                z.writestr('images/'+sha+'.jpg',next(v for v in data.values() if hashlib.sha256(v).hexdigest()==sha))
        jobs.append({'job_id':jid,'asset':path.name,'post_ids':[p['post_id'] for p in batch],'split':'calibration','sha256':digest(path),'bytes':path.stat().st_size,'manifest_sha256':hashlib.sha256(raw).hexdigest(),'image_references':sum(len(p['images']) for p in batch)})
    catalog={'dataset_version':'data-v1','repository':'example/repo','post_count':4,'image_references':5,'unique_images':4,'jobs':jobs}
    atomic_write(root/'data/catalog.json',canonical(catalog))
    return build_index(root)


class ScreeningTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.index=source_fixture(self.root)
        self.store=ScreeningStore(self.root/'private/screening/data-v1.sqlite3',self.index)

    def tearDown(self):
        self.temp.cleanup()

    def test_exclusion_propagates_duplicates_and_undo_restores(self):
        s=self.store.apply(['1'],'exclude','sexual_content',0)
        self.assertEqual(s['effective_excluded_ids'],['1','2'])
        self.assertEqual(s['counts'],dict(include=0,exclude=1,linked_exclude=1,hold=0,pending=2))
        self.assertEqual(self.store.undo(s['revision'])['counts']['pending'],4)
        self.assertEqual(ScreeningStore(self.store.path,self.index).snapshot()['counts']['pending'],4)

    def test_hold_and_unseen_are_not_complete_and_edits_revoke(self):
        with self.assertRaises(ValueError):self.store.complete(0,'human_review_complete')
        with self.assertRaises(ValueError):build(self.root)
        s=self.store.apply(['1','2','3','4'],'include','',0)
        s=self.store.apply(['4'],'hold','uncertain',s['revision'])
        with self.assertRaises(ValueError):self.store.complete(s['revision'],'human_review_complete')
        s=self.store.apply(['4'],'include','',s['revision'])
        s=self.store.complete(s['revision'],'human_review_complete')
        receipt=self.store.completed_receipt()
        self.assertFalse(receipt['production_authorized'])
        self.assertEqual(len(receipt['included_post_ids']),4)
        self.store.apply(['1'],'exclude','sexual_content',s['revision'])
        with self.assertRaises(ValueError):self.store.completed_receipt()

    def test_atomic_conflict_unknown_ids_and_bulk_preserves_exclusions(self):
        s=self.store.apply(['1'],'exclude','sexual_content',0)
        with self.assertRaises(FileExistsError):self.store.apply(['1'],'include','',0)
        with self.assertRaises(ValueError):self.store.apply(['999'],'include','',s['revision'])
        s=self.store.apply(['1','2','3','4'],'include','',s['revision'],pending_only=True)
        self.assertEqual(s['decisions']['1']['decision'],'exclude')
        self.assertNotIn('2',s['decisions'])
        self.assertEqual(s['counts']['include'],2)

    def test_new_bundles_physically_omit_excluded_images_and_source_unchanged(self):
        before={p.name:digest(p) for p in (self.root/'dist/data-v1').iterdir()}
        s=self.store.apply(['1'],'exclude','sexual_content',0)
        s=self.store.apply(['3','4'],'include','',s['revision'])
        self.store.complete(s['revision'],'human_review_complete')
        c=build(self.root)
        forbidden=set(self.store.export()['excluded_image_sha256'])
        self.assertEqual(c['post_count'],2)
        self.assertEqual({p for j in c['jobs'] for p in j['post_ids']},{'3','4'})
        for job in c['jobs']:
            with zipfile.ZipFile(self.root/'dist'/c['dataset_version']/job['asset']) as z:
                self.assertFalse({Path(x).stem for x in z.namelist()} & forbidden)
                self.assertEqual(set(z.namelist()),{'manifest.json'}|{i['path'] for p in json.loads(z.read('manifest.json'))['posts'] for i in p['images']})
        self.assertEqual(before,{p.name:digest(p) for p in (self.root/'dist/data-v1').iterdir()})
        verify_local_screening(c,self.root)
        with self.assertRaises(ValueError):require_launch({'schema_version':'v3-1','run_id':'test'},c,self.root)
        s=self.store.snapshot();self.store.apply(['3'],'hold','uncertain',s['revision'])
        with self.assertRaises(ValueError):verify_local_screening(c,self.root)

    def test_http_metadata_only_start_and_csrf_protection(self):
        server=ScreeningServer(('127.0.0.1',0),self.index,self.store.path,self.root/'dist/data-v1')
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base=f'http://127.0.0.1:{server.server_port}'
        try:
            with urlopen(base+'/api/summary') as r:s=json.load(r)
            self.assertNotIn('posts',s);self.assertNotIn('images',s)
            with urlopen(base+'/api/page?size=24&q=2') as r:page=json.load(r)
            self.assertEqual(len(page['posts']),1);self.assertEqual(len(page['posts'][0]['images']),2)
            payload=canonical({'post_ids':['1'],'decision':'exclude','reason':'sexual_content','revision':0})
            with self.assertRaises(HTTPError) as err:urlopen(Request(base+'/api/decisions',data=payload,headers={'Origin':'https://example.com','X-Review-Token':s['token']}))
            self.assertEqual(err.exception.code,403)
            with urlopen(Request(base+'/api/decisions',data=payload,headers={'Origin':base,'X-Review-Token':s['token']})) as r:self.assertEqual(json.load(r)['counts']['linked_exclude'],1)
            with urlopen(base+'/api/export') as r:export=json.load(r)
            self.assertFalse(export['production_authorized']);self.assertEqual(export['included_post_ids'],[])
        finally:
            server.shutdown();server.server_close();thread.join()
