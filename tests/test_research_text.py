"""Text retries recover interruptions without modifying accepted queue records."""
import argparse
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pipeline_production.common import atomic_write, canonical
from pipeline_production.git_queue import Conflict
from tools import research_text
import test_batch_runtime as fixture


class TextFetchTests(unittest.TestCase):
    def test_retry_failure_then_success_preserves_old_records(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            legacy = folder / 'context' / '101.json'
            old = canonical(dict(post_id='101', state='technical_failure', text=None))
            atomic_write(legacy, old)
            calls = []
            def fetch(pid, path):
                calls.append(path)
                value = dict(post_id=pid, state='available' if len(calls) >= 3 else 'technical_failure',
                             text='recovered' if len(calls) >= 3 else None)
                atomic_write(path, canonical(value)); return value
            result = research_text.fetch_text(folder, '101', fetch=fetch, sleep=lambda _: None)
            self.assertEqual(result['text'], 'recovered')
            self.assertEqual(result['attempts_this_call'], 3)
            self.assertEqual(legacy.read_bytes(), old)
            self.assertEqual(len(set(calls)), 3)
            self.assertEqual(research_text.fetch_text(folder, '101')['attempts_this_call'], 0)
            research_text.fetch_text(folder, '101', refresh=True, fetch=fetch)
            self.assertEqual(len(calls), 4)

    def test_process_interruption_does_not_prohibit_next_request(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            def interrupted(pid, path):
                raise OSError('process interrupted')
            with self.assertRaises(OSError):
                research_text.fetch_text(folder, '101', fetch=interrupted)
            def recovered(pid, path):
                value = dict(post_id=pid, state='available', text='recovered')
                atomic_write(path, canonical(value)); return value
            self.assertEqual(research_text.fetch_text(folder, '101', fetch=recovered)['text'], 'recovered')

    def test_terminal_failure_returns_and_later_call_can_retry(self):
        with tempfile.TemporaryDirectory() as temp:
            def failed(pid, path):
                value = dict(post_id=pid, state='technical_failure', text=None, code=503)
                atomic_write(path, canonical(value)); return value
            for _ in range(2):
                result = research_text.fetch_text(Path(temp), '101', attempts=2, fetch=failed, sleep=lambda _: None)
                self.assertEqual(result['attempts_this_call'], 2)
            self.assertEqual(len(list((Path(temp) / 'context-retries' / '101').glob('*.json'))), 5)


class TextGuardTests(unittest.TestCase):
    setUp = fixture.BatchRuntimeTests.setUp
    tearDown = fixture.BatchRuntimeTests.tearDown
    call = fixture.BatchRuntimeTests.call
    claimed = fixture.BatchRuntimeTests.claimed
    answer = fixture.BatchRuntimeTests.answer

    def test_correct_draft_id_no_git_and_deferred_post_stays_blocked(self):
        jid, folder, manifest = self.claimed()
        current = self.call('next', job=jid)
        args = argparse.Namespace(config=str(self.path), worker=self.config['worker_ids'][0], job=jid, refresh=False, attempts=10)
        with patch.object(research_text, 'ROOT', self.root), \
             patch.object(research_text, 'fetch_text', return_value={'text': 'synthetic'}) as fetch, \
             patch.object(fixture.BatchQueue, '__init__', side_effect=AssertionError('Git called')):
            research_text.run(args)
            self.assertEqual(fetch.call_args.args[1], current['post_id'])
            self.call('defer', job=jid, post=current['post_id'], reason='approval_required')
            with self.assertRaises(Conflict):
                research_text.run(args)
            self.assertEqual(fetch.call_count, 1)


if __name__ == '__main__':
    unittest.main()
