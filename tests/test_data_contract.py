import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from pipeline import contract
from pipeline.bundles import unpack
from pipeline.collect import aggregate_hair
from pipeline.common import canonical, digest
from pipeline.context import budget, project


def valid_record():
    post = {'post_id': '123', 'images': [{'media_index': 1, 'sha256': 'a' * 64}]}
    row = contract.template(post, {'run_id': 'test'}, worker_id='test-01')
    row['execution']['finished_at'] = row['execution']['started_at']
    row['images'][0].update(viewed=True, attributes={k: contract.answer('unknown', reason='ambiguous') for k in contract.IMAGE_FIELDS})
    return post, row


class ContractTests(unittest.TestCase):
    def test_template_and_missing_images_are_rejected(self):
        post, row = valid_record()
        contract.validate(row, post, {'run_id': 'test'})
        row['images'] = []
        with self.assertRaises(AssertionError):
            contract.validate(row, post, {'run_id': 'test'})
        with self.assertRaises(AssertionError):
            contract.validate(contract.template(post, {}), post, {})

    def test_unknown_not_false_and_positive_wins(self):
        _, r = valid_record()
        self.assertEqual(aggregate_hair(r['images'], 'red'), 'unknown')
        i = copy.deepcopy(r['images'][0])
        i['attributes']['has_red_hair'] = contract.answer('observed', True, '', 'visible')
        self.assertEqual(aggregate_hair([i, *r['images']], 'red'), 'true')
        i['attributes']['has_red_hair']['value'] = False
        self.assertEqual(aggregate_hair([i, *r['images']], 'red'), 'unknown')
        self.assertEqual(aggregate_hair([i], 'red'), 'false')

    def test_creation_without_source_rejected(self):
        post, row = valid_record()
        row['context']['attributes']['creation'] = contract.answer('observed', 'original', '', 'not found on search')
        with self.assertRaises(AssertionError):
            contract.validate(row, post, {'run_id': 'test'})

    def test_metrics_and_quoted_post_do_not_leak(self):
        payload = {'code': 200, 'status': {'id': '123', 'type': 'status', 'text': 'original', 'likes': 999,
                   'quote': {'text': 'fan art'}, 'author': {'screen_name': 'abc', 'followers': 100}}}
        out = project(payload, '123')
        self.assertEqual(out['text'], 'original')
        self.assertNotIn('likes', json.dumps(out))
        self.assertNotIn('followers', json.dumps(out))
        self.assertNotIn('fan art', json.dumps(out))
        self.assertEqual(project(payload, '456')['state'], 'unavailable')

    def test_search_count_and_deadline_enforced(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / 'budget.json'
            self.assertTrue(budget(p, 'search', clock=lambda: 0)['permitted'])
            self.assertTrue(budget(p, 'search', clock=lambda: 1)['permitted'])
            self.assertFalse(budget(p, 'search', clock=lambda: 2)['permitted'])
            self.assertFalse(budget(p, 'page', clock=lambda: 60)['permitted'])

    def test_zip_traversal_rejected_even_with_matching_zip_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / 'bundle.zip'
            manifest = {'job_id': 'job-1', 'posts': [{'post_id': '123', 'images': []}]}
            with zipfile.ZipFile(p, 'w') as z:
                z.writestr('manifest.json', canonical(manifest))
                z.writestr('../escape.txt', 'no')
            job = {'job_id': 'job-1', 'post_ids': ['123'], 'sha256': digest(p),
                   'manifest_sha256': hashlib.sha256(canonical(manifest)).hexdigest()}
            with self.assertRaises(AssertionError):
                unpack(p, job, Path(temp) / 'out')
            self.assertFalse((Path(temp) / 'escape.txt').exists())


if __name__ == '__main__':
    unittest.main()
