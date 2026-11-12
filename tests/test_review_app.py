import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from pipeline.review_app import ReviewServer, ReviewStore


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


if __name__ == '__main__':
    unittest.main()
