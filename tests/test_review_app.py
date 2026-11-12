import json
import hashlib
import io
import shutil
import zipfile
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from pipeline.review_app import ReviewServer, ReviewStore, load_pilot


class HumanReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.dataset = {'run_id': 'example', 'fingerprint': 'abc123',
                        'posts': [{'post_id': '123', 'images': [{'media_index': 1}]}]}
        self.path = self.root / 'private/reviews.json'
        self.item = {'post_id': '123', 'status': 'issue', 'note': '髪色を確認',
                     'flags': ['image1.has_red_hair'], 'displayed_media': [1], 'revision': 0}

    def tearDown(self):
        self.temp.cleanup()

    def test_saved_review_reloads_without_changing_labels(self):
        before = json.dumps(self.dataset, sort_keys=True)
        store = ReviewStore(self.path, self.dataset)
        result = store.save(self.item)
        reloaded = ReviewStore(self.path, self.dataset).snapshot()
        self.assertEqual(reloaded['reviews']['123'], result)
        self.assertEqual(result['note'], '髪色を確認')
        self.assertEqual(result['revision'], 1)
        self.assertEqual(json.dumps(self.dataset, sort_keys=True), before)
        self.assertEqual(reloaded['method'], 'human_quick_review_with_ai_labels_visible')

    def test_conflict_and_invalid_inputs_do_not_overwrite_saved_review(self):
        store = ReviewStore(self.path, self.dataset)
        store.save(self.item)
        before = self.path.read_bytes()
        with self.assertRaises(FileExistsError):
            store.save(dict(self.item, status='ok'))
        for bad in [dict(self.item, post_id='999'), dict(self.item, displayed_media=[2]),
                    dict(self.item, note='x' * 5001), dict(self.item, status='approved')]:
            with self.assertRaises(ValueError):
                store.save(bad)
        self.assertEqual(self.path.read_bytes(), before)
        with self.assertRaises(ValueError):
            ReviewStore(self.path, dict(self.dataset, fingerprint='different'))

    def test_http_persistence_export_and_origin_protection(self):
        server = ReviewServer(('127.0.0.1', 0), self.dataset, {}, self.path)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        try:
            with urlopen(base + '/api/data') as response:
                data = json.load(response)
            payload = json.dumps(self.item).encode()
            for origin, token in [('https://example.com', data['token']), (base, 'bad')]:
                with self.assertRaises(HTTPError) as caught:
                    urlopen(Request(base + '/api/review', data=payload, headers={'Origin': origin, 'X-Review-Token': token}))
                self.assertEqual(caught.exception.code, 403)
            self.assertFalse(self.path.exists())
            with urlopen(Request(base + '/api/review', data=payload, headers={'Origin': base, 'X-Review-Token': data['token']})) as response:
                self.assertEqual(json.load(response)['status'], 'issue')
            with urlopen(base + '/api/export') as response:
                exported = json.load(response)
            self.assertEqual(exported['reviews']['123']['flags'], ['image1.has_red_hair'])
            with self.assertRaises(HTTPError) as caught:
                urlopen(base + '/images/../../private/reviews.json')
            self.assertEqual(caught.exception.code, 404)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_image_route_rejects_bytes_changed_after_loading(self):
        payload=b'synthetic image bytes'; sha=hashlib.sha256(payload).hexdigest()
        path=self.root/'image.jpg'; path.write_bytes(payload)
        server=ReviewServer(('127.0.0.1',0),self.dataset,{sha:path},self.path)
        thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        try:
            url=f'http://127.0.0.1:{server.server_port}/images/{sha}.jpg'
            with urlopen(url) as response:self.assertEqual(response.read(),payload)
            path.write_bytes(b'changed bytes')
            with self.assertRaises(HTTPError) as caught:urlopen(url)
            self.assertEqual(caught.exception.code,409)
        finally:
            server.shutdown(); server.server_close(); thread.join()

    def test_v3_review_uses_screened_source_and_omits_refused_duplicates(self):
        from pipeline import worker, disposition
        from pipeline.common import atomic_write, canonical, digest
        from pipeline.prepare_run import prepare
        from pipeline.prepare_screened import build
        from pipeline.screening import ScreeningStore
        from pipeline.toolchain import FILES
        from test_screening import source_fixture
        from test_worker_v3 import synthetic_answer
        for name in set(FILES)|{'pipeline/contract_v3.py','docs/LABELING_V3.md'}:
            dest=self.root/name; dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(worker.ROOT/name,dest)
        index=source_fixture(self.root)
        screening=ScreeningStore(self.root/'private/screening/data-v1.sqlite3',index)
        s=screening.apply(['1','2','3','4'],'include','',0)
        screening.complete(s['revision'],'human_review_complete')
        with redirect_stdout(io.StringIO()):
            catalog=build(self.root); config=prepare('synthetic-review','calibration',root=self.root)
        recovered=self.root/'recovered'
        for job in catalog['jobs']:
            with zipfile.ZipFile(self.root/'dist'/catalog['dataset_version']/job['asset']) as z:
                manifest=json.loads(z.read('manifest.json'))
            answers=[disposition.create(p,worker.provenance(config,manifest),'synthetic','image_tool_refusal') if p['post_id']=='1'
                     else synthetic_answer(p,config,manifest,'synthetic') for p in manifest['posts']]
            raw=b''.join(canonical(r) for r in answers)
            atomic_write(recovered/job['job_id']/'labels.jsonl',raw)
            atomic_write(recovered/job['job_id']/'state.json',canonical({'status':'completed','result_sha256':hashlib.sha256(raw).hexdigest()}))
        with patch('pipeline.worker.ROOT',self.root),patch('pipeline.review_app.bundle_root',side_effect=AssertionError('must not use original archive')):
            data,images=load_pilot(self.root,self.root/'runs/synthetic-review.json',recovered)
        self.assertEqual({p['post_id'] for p in data['posts']},{'3','4'})
        self.assertEqual(data['exclusions'],[{'post_id':'1','reason':'policy_refusal'}])
        self.assertEqual(len(images),2)
        self.assertTrue(all(digest(path)==sha for sha,path in images.items()))


if __name__ == '__main__':
    unittest.main()
