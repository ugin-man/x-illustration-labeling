"""Synthetic records only; exercise bundling, worker I/O, queue, and collector together."""
from pathlib import Path
import json
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from pipeline import contract
from pipeline.common import atomic_write, canonical
from pipeline.worker import ROOT, check_config, main, provenance


class EndToEndTests(unittest.TestCase):
    def test_real_bundle_io_with_synthetic_unknown_answers(self):
        config_path = ROOT / 'runs/pilot-v2-001.json'
        if not config_path.exists():
            self.skipTest('Run not yet frozen')
        # This test reads a real local bundle but never views/classifies pixels.
        if not (ROOT / 'dist/data-v1/cal-0001.zip').exists():
            self.skipTest('Local preparation bundles not available; cloud unit tests remain offline')
        from pipeline.bundles import unpack
        from pipeline.collect import collect
        from pipeline.git_queue import GitQueue
        config, catalog = check_config(config_path)
        job = catalog['jobs'][0]
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            remote = temp / 'remote.git'
            subprocess.run(['git', 'init', '--bare', '--quiet', str(remote)], check=True)
            manifest = unpack(ROOT / 'dist/data-v1' / job['asset'], job, temp / 'input')
            rows = {}
            for post in manifest['posts']:
                row = contract.template(post, provenance(config, manifest), 'synthetic-test')
                row['execution']['finished_at'] = row['execution']['started_at']
                for i in row['images']:
                    i['read_error'] = 'synthetic_test_no_pixel_inspection'
                    i['attributes'] = {k: contract.answer('technical_failure', reason='synthetic_test') for k in contract.IMAGE_FIELDS}
                contract.validate(row, post, provenance(config, manifest))
                rows[post['post_id']] = row
            with GitQueue(remote, config['run_id'], config['catalog_sha256']) as q:
                lease = q.reserve(job['job_id'], 'synthetic-test')
                q.checkpoint(job['job_id'], lease['token'], rows, manifest=manifest)
                q.finish(job['job_id'], lease['token'], job['post_ids'])
            collect(config_path, temp / 'collected', remote=remote)
            receipt = json.loads((temp / 'collected/receipt.json').read_text())
            self.assertEqual(receipt['processed_posts'], 50)
            self.assertEqual(receipt['counts']['posts_with_visual_failure'], 50)
            self.assertEqual(receipt['counts']['context_pending'], 50)


if __name__ == '__main__':
    unittest.main()
